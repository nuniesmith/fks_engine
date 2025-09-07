"""
Authentication utilities for API security.

This module provides comprehensive authentication functionality including JWT tokens,
role-based access control, dependency injection for FastAPI, and security utilities.
"""

import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union

import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from passlib.context import CryptContext

# Configuration constants with environment variable support
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
AUTHELIA_JWT_SECRET = os.getenv("AUTHELIA_JWT_SECRET", None)
AUTHELIA_JWT_ALGORITHM = os.getenv("AUTHELIA_JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token scheme
security = HTTPBearer(auto_error=False)


class TokenType(Enum):
    """Token types for different purposes."""

    ACCESS = "access"
    REFRESH = "refresh"
    RESET = "reset"
    VERIFICATION = "verification"


class AuthenticationError(Exception):
    """Base authentication error."""

    pass


class TokenExpiredError(AuthenticationError):
    """Token has expired."""

    pass


class InvalidTokenError(AuthenticationError):
    """Token is invalid."""

    pass


class InsufficientPermissionsError(AuthenticationError):
    """User lacks required permissions."""

    pass


@dataclass
class TokenPayload:
    """Structured token payload."""

    sub: str  # Subject (user ID)
    username: Optional[str] = None
    email: Optional[str] = None
    roles: List[str] = None
    permissions: List[str] = None
    token_type: str = TokenType.ACCESS.value
    iat: Optional[int] = None  # Issued at
    exp: Optional[int] = None  # Expires at
    jti: Optional[str] = None  # JWT ID

    def __post_init__(self):
        if self.roles is None:
            self.roles = []
        if self.permissions is None:
            self.permissions = []


@dataclass
class UserInfo:
    """User information extracted from token."""

    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    roles: List[str] = None
    permissions: List[str] = None
    is_active: bool = True
    is_verified: bool = True

    def __post_init__(self):
        if self.roles is None:
            self.roles = []
        if self.permissions is None:
            self.permissions = []

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role.lower() in [r.lower() for r in self.roles]

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission."""
        return permission.lower() in [p.lower() for p in self.permissions]

    def has_any_role(self, roles: List[str]) -> bool:
        """Check if user has any of the specified roles."""
        return any(self.has_role(role) for role in roles)

    def has_all_roles(self, roles: List[str]) -> bool:
        """Check if user has all of the specified roles."""
        return all(self.has_role(role) for role in roles)

    def has_any_permission(self, permissions: List[str]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(self.has_permission(perm) for perm in permissions)

    def has_all_permissions(self, permissions: List[str]) -> bool:
        """Check if user has all of the specified permissions."""
        return all(self.has_permission(perm) for perm in permissions)


class JWTManager:
    """JWT token management."""

    def __init__(
        self,
        secret_key: str = JWT_SECRET,
        algorithm: str = JWT_ALGORITHM,
        access_token_expire_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES,
        refresh_token_expire_days: int = REFRESH_TOKEN_EXPIRE_DAYS,
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days

        # Validate configuration
        if not self.secret_key or len(self.secret_key) < 32:
            logger.warning(
                "JWT secret key is too short or missing. Use a secure random key."
            )

    def create_token(
        self,
        user_id: str,
        username: Optional[str] = None,
        email: Optional[str] = None,
        roles: List[str] = None,
        permissions: List[str] = None,
        token_type: TokenType = TokenType.ACCESS,
        expires_delta: Optional[timedelta] = None,
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a JWT token.

        Args:
            user_id: User identifier
            username: Username
            email: User email
            roles: User roles
            permissions: User permissions
            token_type: Type of token
            expires_delta: Custom expiration time
            additional_claims: Additional claims to include

        Returns:
            str: Encoded JWT token
        """
        now = datetime.now(timezone.utc)

        # Set expiration based on token type and custom delta
        if expires_delta:
            expire = now + expires_delta
        elif token_type == TokenType.ACCESS:
            expire = now + timedelta(minutes=self.access_token_expire_minutes)
        elif token_type == TokenType.REFRESH:
            expire = now + timedelta(days=self.refresh_token_expire_days)
        else:
            expire = now + timedelta(hours=24)  # Default 24 hours

        # Create payload
        payload = {
            "sub": user_id,
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
            "type": token_type.value,
            "jti": secrets.token_urlsafe(16),  # Unique token ID
        }

        # Add optional fields
        if username:
            payload["username"] = username
        if email:
            payload["email"] = email
        if roles:
            payload["roles"] = roles
        if permissions:
            payload["permissions"] = permissions

        # Add additional claims
        if additional_claims:
            payload.update(additional_claims)

        # Encode token
        try:
            token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
            logger.debug(f"Created {token_type.value} token for user {user_id}")
            return token
        except Exception as e:
            logger.error(f"Failed to create token: {e}")
            raise InvalidTokenError("Failed to create token")

    def decode_token(self, token: str, verify_exp: bool = True) -> TokenPayload:
        """
        Decode and validate a JWT token.

        Args:
            token: JWT token to decode
            verify_exp: Whether to verify expiration

        Returns:
            TokenPayload: Decoded token payload

        Raises:
            TokenExpiredError: If token has expired
            InvalidTokenError: If token is invalid
        """
        try:
            # First try to decode with Authentik JWT secret if available
            if AUTHELIA_JWT_SECRET:
                try:
                    payload = jwt.decode(
                        token,
                        AUTHELIA_JWT_SECRET,
                        algorithms=[AUTHELIA_JWT_ALGORITHM],
                        options={"verify_exp": verify_exp},
                    )
                    logger.debug("Token validated with Authentik JWT secret")
                except jwt.InvalidTokenError:
                    # If Authentik validation fails, try regular JWT
                    payload = jwt.decode(
                        token,
                        self.secret_key,
                        algorithms=[self.algorithm],
                        options={"verify_exp": verify_exp},
                    )
                    logger.debug("Token validated with regular JWT secret")
            else:
                # No Authentik secret configured, use regular JWT
                payload = jwt.decode(
                    token,
                    self.secret_key,
                    algorithms=[self.algorithm],
                    options={"verify_exp": verify_exp},
                )

            # Create structured payload
            token_payload = TokenPayload(
                sub=payload["sub"],
                username=payload.get("username"),
                email=payload.get("email"),
                roles=payload.get("roles", []),
                permissions=payload.get("permissions", []),
                token_type=payload.get("type", TokenType.ACCESS.value),
                iat=payload.get("iat"),
                exp=payload.get("exp"),
                jti=payload.get("jti"),
            )

            logger.debug(f"Successfully decoded token for user {token_payload.sub}")
            return token_payload

        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            raise InvalidTokenError(f"Invalid token: {str(e)}")
        except Exception as e:
            logger.error(f"Token decode error: {e}")
            raise InvalidTokenError("Token decode failed")

    def refresh_token(self, refresh_token: str) -> Dict[str, str]:
        """
        Create new access token from refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            Dict containing new access and refresh tokens
        """
        try:
            # Decode refresh token
            payload = self.decode_token(refresh_token, verify_exp=True)

            # Verify it's a refresh token
            if payload.token_type != TokenType.REFRESH.value:
                raise InvalidTokenError("Invalid token type for refresh")

            # Create new tokens
            new_access_token = self.create_token(
                user_id=payload.sub,
                username=payload.username,
                email=payload.email,
                roles=payload.roles,
                permissions=payload.permissions,
                token_type=TokenType.ACCESS,
            )

            new_refresh_token = self.create_token(
                user_id=payload.sub,
                username=payload.username,
                email=payload.email,
                roles=payload.roles,
                permissions=payload.permissions,
                token_type=TokenType.REFRESH,
            )

            logger.info(f"Refreshed tokens for user {payload.sub}")

            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
            }

        except (TokenExpiredError, InvalidTokenError):
            raise
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            raise InvalidTokenError("Token refresh failed")


# Global JWT manager instance
jwt_manager = JWTManager()


# Backward compatibility functions
def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token (backward compatible).

    Args:
        data: Data to encode in the token
        expires_delta: Optional expiration time delta

    Returns:
        str: Encoded JWT token
    """
    # Extract user_id from data
    user_id = data.get("sub", data.get("user_id", ""))
    username = data.get("username")
    email = data.get("email")
    roles = data.get("roles", [])
    permissions = data.get("permissions", [])

    return jwt_manager.create_token(
        user_id=user_id,
        username=username,
        email=email,
        roles=roles,
        permissions=permissions,
        expires_delta=expires_delta,
    )


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT token (backward compatible).

    Args:
        token: JWT token to decode

    Returns:
        Dict containing the token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt_manager.decode_token(token)

        # Convert to dict for backward compatibility
        return {
            "sub": payload.sub,
            "username": payload.username,
            "email": payload.email,
            "roles": payload.roles,
            "permissions": payload.permissions,
            "token_type": payload.token_type,
            "iat": payload.iat,
            "exp": payload.exp,
            "jti": payload.jti,
        }

    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def authenticate_user(token: str) -> Dict[str, Any]:
    """
    Authenticate a user with a JWT token (backward compatible).

    Args:
        token: JWT token

    Returns:
        Dict containing user information from the token

    Raises:
        HTTPException: If authentication fails
    """
    payload = decode_token(token)

    # Verify that the token contains user information
    if "sub" not in payload or not payload["sub"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token content",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def get_auth_token(request: Request) -> Optional[str]:
    """
    Extract the JWT token from the request.

    Args:
        request: FastAPI request object

    Returns:
        str: JWT token if present, otherwise None
    """
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer":
            return token

    # Try X-API-Key header as fallback
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key

    # Try query parameter as last resort (not recommended for production)
    token_param = request.query_params.get("token")
    if token_param:
        logger.warning("Token provided via query parameter - this is insecure")
        return token_param

    return None


# FastAPI dependency functions
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> UserInfo:
    """
    Get the current authenticated user.

    Args:
        credentials: HTTP authorization credentials

    Returns:
        UserInfo: Current user information

    Raises:
        HTTPException: If authentication fails
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt_manager.decode_token(credentials.credentials)

        user_info = UserInfo(
            user_id=payload.sub,
            username=payload.username,
            email=payload.email,
            roles=payload.roles,
            permissions=payload.permissions,
        )

        logger.debug(f"Authenticated user: {user_info.user_id}")
        return user_info

    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_active_user(
    current_user: UserInfo = Depends(get_current_user),
) -> UserInfo:
    """
    Get the current active user.

    Args:
        current_user: Current authenticated user

    Returns:
        UserInfo: Current active user

    Raises:
        HTTPException: If user is not active
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
        )

    return current_user


async def get_current_verified_user(
    current_user: UserInfo = Depends(get_current_active_user),
) -> UserInfo:
    """
    Get the current verified user.

    Args:
        current_user: Current active user

    Returns:
        UserInfo: Current verified user

    Raises:
        HTTPException: If user is not verified
    """
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified"
        )

    return current_user


# Role and permission checking utilities
def require_roles(*roles: str) -> Callable:
    """
    Create a dependency that requires specific roles.

    Args:
        *roles: Required roles

    Returns:
        Dependency function
    """

    def check_roles(
        current_user: UserInfo = Depends(get_current_active_user),
    ) -> UserInfo:
        if not current_user.has_any_role(list(roles)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(roles)}",
            )
        return current_user

    return check_roles


def require_permissions(*permissions: str) -> Callable:
    """
    Create a dependency that requires specific permissions.

    Args:
        *permissions: Required permissions

    Returns:
        Dependency function
    """

    def check_permissions(
        current_user: UserInfo = Depends(get_current_active_user),
    ) -> UserInfo:
        if not current_user.has_any_permission(list(permissions)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required permissions: {', '.join(permissions)}",
            )
        return current_user

    return check_permissions


def require_admin(
    current_user: UserInfo = Depends(get_current_active_user),
) -> UserInfo:
    """
    Require admin role.

    Args:
        current_user: Current user

    Returns:
        UserInfo: Admin user
    """
    if not current_user.has_role("admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user


# Password utilities
def hash_password(password: str) -> str:
    """
    Hash a password.

    Args:
        password: Plain text password

    Returns:
        str: Hashed password
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password

    Returns:
        bool: True if password matches
    """
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_strength(password: str) -> List[str]:
    """
    Validate password strength.

    Args:
        password: Password to validate

    Returns:
        List[str]: List of validation errors (empty if valid)
    """
    errors = []

    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters long"
        )

    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")

    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")

    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")

    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        errors.append("Password must contain at least one special character")

    return errors


# Token utilities
def create_reset_token(user_id: str, expires_in_hours: int = 1) -> str:
    """
    Create a password reset token.

    Args:
        user_id: User identifier
        expires_in_hours: Token expiration in hours

    Returns:
        str: Reset token
    """
    return jwt_manager.create_token(
        user_id=user_id,
        token_type=TokenType.RESET,
        expires_delta=timedelta(hours=expires_in_hours),
    )


def create_verification_token(
    user_id: str, email: str, expires_in_hours: int = 24
) -> str:
    """
    Create an email verification token.

    Args:
        user_id: User identifier
        email: User email
        expires_in_hours: Token expiration in hours

    Returns:
        str: Verification token
    """
    return jwt_manager.create_token(
        user_id=user_id,
        email=email,
        token_type=TokenType.VERIFICATION,
        expires_delta=timedelta(hours=expires_in_hours),
    )


def refresh_tokens(refresh_token: str) -> Dict[str, str]:
    """
    Refresh access and refresh tokens.

    Args:
        refresh_token: Valid refresh token

    Returns:
        Dict containing new tokens
    """
    return jwt_manager.refresh_token(refresh_token)


# Security utilities
def generate_api_key() -> str:
    """
    Generate a secure API key.

    Returns:
        str: Generated API key
    """
    return secrets.token_urlsafe(32)


def constant_time_compare(a: str, b: str) -> bool:
    """
    Compare two strings in constant time to prevent timing attacks.

    Args:
        a: First string
        b: Second string

    Returns:
        bool: True if strings are equal
    """
    return secrets.compare_digest(a.encode(), b.encode())


# Configuration and health check
def get_auth_config() -> Dict[str, Any]:
    """
    Get authentication configuration.

    Returns:
        Dict: Authentication configuration
    """
    return {
        "jwt_algorithm": JWT_ALGORITHM,
        "access_token_expire_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
        "refresh_token_expire_days": REFRESH_TOKEN_EXPIRE_DAYS,
        "password_min_length": PASSWORD_MIN_LENGTH,
        "secret_key_configured": bool(JWT_SECRET and len(JWT_SECRET) >= 32),
    }


def auth_health_check() -> Dict[str, Any]:
    """
    Perform health check on authentication system.

    Returns:
        Dict: Health check results
    """
    health = {
        "status": "healthy",
        "jwt_manager": "operational",
        "secret_key": (
            "configured" if JWT_SECRET and len(JWT_SECRET) >= 32 else "missing"
        ),
        "password_hashing": "operational",
    }

    # Test JWT creation and verification
    try:
        test_token = jwt_manager.create_token(
            user_id="test", token_type=TokenType.ACCESS
        )
        jwt_manager.decode_token(test_token)
        health["jwt_operations"] = "operational"
    except Exception as e:
        health["jwt_operations"] = f"failed: {str(e)}"
        health["status"] = "degraded"

    # Test password hashing
    try:
        test_hash = hash_password("test123")
        verify_password("test123", test_hash)
        health["password_operations"] = "operational"
    except Exception as e:
        health["password_operations"] = f"failed: {str(e)}"
        health["status"] = "degraded"

    return health


# Export commonly used items
__all__ = [
    # Backward compatibility
    "create_access_token",
    "decode_token",
    "authenticate_user",
    "get_auth_token",
    # Core classes
    "JWTManager",
    "TokenPayload",
    "UserInfo",
    "TokenType",
    # Exceptions
    "AuthenticationError",
    "TokenExpiredError",
    "InvalidTokenError",
    "InsufficientPermissionsError",
    # Dependencies
    "get_current_user",
    "get_current_active_user",
    "get_current_verified_user",
    "require_roles",
    "require_permissions",
    "require_admin",
    # Password utilities
    "hash_password",
    "verify_password",
    "validate_password_strength",
    # Token utilities
    "create_reset_token",
    "create_verification_token",
    "refresh_tokens",
    # Security utilities
    "generate_api_key",
    "constant_time_compare",
    # Configuration
    "get_auth_config",
    "auth_health_check",
    # Constants
    "JWT_SECRET",
    "JWT_ALGORITHM",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
]
