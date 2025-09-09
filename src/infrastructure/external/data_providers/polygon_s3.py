import io
import os
import time
from typing import Any, Dict, Optional

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query
from infrastructure.external.data_providers.clients.base import BaseClient
from loguru import logger
from pydantic import BaseModel


class PolygonS3Client(BaseClient):
    """
    A client class for fetching Polygon data stored as files in an S3 bucket,
    using custom credentials and endpoint configuration.
    """

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        s3_endpoint: Optional[str] = None,
        bucket: Optional[str] = None,
        metrics: Optional[Any] = None,
    ) -> None:
        """
        Initialize the PolygonS3Client.
        """
        super().__init__(name="PolygonS3Client", metrics=metrics)

        self.access_key_id = access_key_id or os.getenv("POLYGON_S3_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.getenv(
            "POLYGON_S3_SECRET_ACCESS_KEY"
        )
        self.s3_endpoint = s3_endpoint or os.getenv("POLYGON_S3_ENDPOINT")
        self.bucket = bucket or os.getenv("POLYGON_S3_BUCKET")

        if not all(
            [self.access_key_id, self.secret_access_key, self.s3_endpoint, self.bucket]
        ):
            raise ValueError(
                "All credentials and configuration (access key, secret key, endpoint, bucket) must be provided."
            )

        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            endpoint_url=self.s3_endpoint,
        )
        logger.info(
            f"Initialized PolygonS3Client for bucket: {self.bucket} at {self.s3_endpoint}"
        )

    def fetch_file(self, key: str, file_format: str = "csv") -> Optional[pd.DataFrame]:
        """
        Fetch a file from the specified S3 bucket and return its content as a pandas DataFrame.
        """
        start_time = time.time()

        try:
            logger.info(f"Fetching file from S3: Bucket={self.bucket}, Key={key}")

            # Record the operation start
            self.metrics.record_api_call(
                client_name=self.name,
                endpoint=f"fetch_file_{file_format}",
                success=False,  # Will update to True if successful
                duration_ms=0,  # Will update with actual duration
            )

            response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
            file_content = response["Body"].read().decode("utf-8")

            if file_format.lower() == "csv":
                df = pd.read_csv(io.StringIO(file_content))
            else:
                logger.error(f"Unsupported file format: {file_format}")
                duration_ms = (time.time() - start_time) * 1000
                self.metrics.record_api_call(
                    client_name=self.name,
                    endpoint=f"fetch_file_{file_format}",
                    success=False,
                    duration_ms=duration_ms,
                )
                return None

            logger.info(f"Successfully fetched file: {key} with {len(df)} rows.")

            # Record successful API call
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_api_call(
                client_name=self.name,
                endpoint=f"fetch_file_{file_format}",
                success=True,
                duration_ms=duration_ms,
            )

            # Record operation duration
            self.record_operation_duration(
                operation_name="fetch_file",
                symbol=key.split("/")[-1].split(".")[
                    0
                ],  # Extract symbol from filename if possible
                timeframe="file",
                duration=(time.time() - start_time),
                update_type="s3",
            )

            return df

        except ClientError as e:
            logger.error(f"ClientError fetching file from S3: {e}")
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_api_call(
                client_name=self.name,
                endpoint=f"fetch_file_{file_format}",
                success=False,
                duration_ms=duration_ms,
            )
            return None

        except Exception as e:
            logger.error(f"Unexpected error fetching file from S3: {e}")
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.record_api_call(
                client_name=self.name,
                endpoint=f"fetch_file_{file_format}",
                success=False,
                duration_ms=duration_ms,
            )
            return None

    def get_health_status(self) -> bool:
        """
        Check the health of the S3 connection by listing objects in the bucket.
        """
        try:
            response = self.s3_client.list_objects_v2(Bucket=self.bucket, MaxKeys=1)
            health_status = "Contents" in response or "KeyCount" in response

            # Record health check result
            self.metrics.record_health_check(
                client_name=self.name, success=health_status
            )
            self.metrics.record_client_availability(
                client_name=self.name, available=health_status
            )

            return health_status

        except Exception as e:
            logger.error(f"S3 health check failed: {e}")

            # Record failed health check
            self.metrics.record_health_check(client_name=self.name, success=False)
            self.metrics.record_client_availability(
                client_name=self.name, available=False
            )

            return False

    def _process_data(self, data: Any) -> pd.DataFrame:
        """
        Process data into DataFrame format - S3 client doesn't need this as it directly returns DataFrames.
        """
        # This is a placeholder since we already return DataFrames from fetch_file
        if isinstance(data, pd.DataFrame):
            return data
        return pd.DataFrame(data)

    def get(
        self, key: str, file_format: str = "csv", **kwargs
    ) -> Optional[pd.DataFrame]:
        """
        Standardized get method to match the BaseClient interface.
        """
        return self.fetch_file(key, file_format)


# ==========================
# FastAPI Router Integration
# ==========================

router = APIRouter(prefix="/polygon_s3", tags=["PolygonS3Client"])

# Global PolygonS3Client instance
try:
    polygon_s3_client = PolygonS3Client()
except ValueError as e:
    logger.warning(f"Failed to initialize PolygonS3Client: {e}")
    polygon_s3_client = None


# Pydantic model for endpoint payload (if needed)
class FetchFilePayload(BaseModel):
    key: str
    file_format: Optional[str] = "csv"


@router.get("/health", summary="Check S3 connection health")
def check_health():
    """
    Endpoint to check the health of the S3 connection.
    """
    if polygon_s3_client is None:
        raise HTTPException(
            status_code=503, detail="PolygonS3Client is not initialized."
        )

    is_healthy = polygon_s3_client.get_health_status()
    if not is_healthy:
        raise HTTPException(status_code=503, detail="S3 connection is not healthy.")
    return {"status": "S3 connection is healthy."}


@router.get("/file", summary="Fetch file from S3")
def fetch_file(
    key: str = Query(
        ..., description="The S3 object key (file path within the bucket)"
    ),
    file_format: str = Query("csv", description="The file format (default: csv)"),
):
    """
    Endpoint to fetch a file from the S3 bucket and return its contents as JSON.
    """
    if polygon_s3_client is None:
        raise HTTPException(
            status_code=503, detail="PolygonS3Client is not initialized."
        )

    df = polygon_s3_client.fetch_file(key, file_format)
    if df is None:
        raise HTTPException(
            status_code=404, detail="File not found or could not be processed."
        )
    # Convert DataFrame to JSON records
    data = df.to_dict(orient="records")
    return {"key": key, "file_format": file_format, "data": data}
