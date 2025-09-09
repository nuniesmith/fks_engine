"""Base transformer components and building blocks"""

import logging
import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class PositionalEncoding(nn.Module):
    """positional encoding with learnable components"""

    def __init__(self, d_model: int, max_len: int = 5000, dropout: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(dropout)

        # Standard sinusoidal encoding
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )

        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)

        self.register_buffer("pe", pe.unsqueeze(0))

        # Learnable component
        self.learnable_pe = nn.Parameter(torch.zeros(1, max_len, d_model))
        nn.init.normal_(self.learnable_pe, std=0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        seq_len = x.size(1)
        # Combine fixed and learnable positional encodings
        pos_encoding = self.pe[:, :seq_len, :] + self.learnable_pe[:, :seq_len, :]
        return self.dropout(x + pos_encoding)


class MultiHeadAttention(nn.Module):
    """Multi-head attention with relative position bias"""

    def __init__(
        self,
        d_model: int,
        nhead: int,
        dropout: float = 0.1,
        use_relative_position: bool = True,
    ):
        super().__init__()
        assert d_model % nhead == 0

        self.d_model = d_model
        self.nhead = nhead
        self.d_k = d_model // nhead
        self.use_relative_position = use_relative_position

        # Linear projections
        self.w_q = nn.Linear(d_model, d_model, bias=False)
        self.w_k = nn.Linear(d_model, d_model, bias=False)
        self.w_v = nn.Linear(d_model, d_model, bias=False)
        self.w_o = nn.Linear(d_model, d_model)

        # Relative position bias
        if use_relative_position:
            self.relative_position_bias = nn.Parameter(
                torch.zeros(nhead, 2 * 256 - 1)  # Max relative distance
            )
            nn.init.normal_(self.relative_position_bias, std=0.02)

        self.dropout = nn.Dropout(dropout)
        self.scale = math.sqrt(self.d_k)

    def _get_relative_position_bias(self, seq_len: int) -> torch.Tensor:
        """Compute relative position bias"""
        if not self.use_relative_position:
            return torch.zeros(
                1,
                self.nhead,
                seq_len,
                seq_len,
                device=self.relative_position_bias.device,
            )

        # Create position indices
        positions = torch.arange(seq_len, device=self.relative_position_bias.device)
        relative_positions = positions.unsqueeze(0) - positions.unsqueeze(1)

        # Clip to valid range
        relative_positions = relative_positions.clamp(-255, 255) + 255

        # Get bias values
        bias = self.relative_position_bias[:, relative_positions]
        return bias.unsqueeze(0)  # Add batch dimension

    def forward(
        self,
        query: torch.Tensor,
        key: torch.Tensor,
        value: torch.Tensor,
        mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        batch_size, seq_len = query.size(0), query.size(1)

        # Linear transformations
        Q = (
            self.w_q(query)
            .view(batch_size, seq_len, self.nhead, self.d_k)
            .transpose(1, 2)
        )
        K = (
            self.w_k(key)
            .view(batch_size, seq_len, self.nhead, self.d_k)
            .transpose(1, 2)
        )
        V = (
            self.w_v(value)
            .view(batch_size, seq_len, self.nhead, self.d_k)
            .transpose(1, 2)
        )

        # Attention scores
        scores = torch.matmul(Q, K.transpose(-2, -1)) / self.scale

        # Add relative position bias
        if self.use_relative_position:
            scores = scores + self._get_relative_position_bias(seq_len)

        # Apply mask
        if mask is not None:
            scores.masked_fill_(mask == 0, -1e9)

        # Attention weights
        attn_weights = F.softmax(scores, dim=-1)
        attn_weights = self.dropout(attn_weights)

        # Context
        context = torch.matmul(attn_weights, V)
        context = (
            context.transpose(1, 2).contiguous().view(batch_size, seq_len, self.d_model)
        )

        return self.w_o(context)


class FeedForwardNetwork(nn.Module):
    """feed-forward network with GLU variant"""

    def __init__(
        self, d_model: int, d_ff: int, dropout: float = 0.1, activation: str = "gelu"
    ):
        super().__init__()

        self.linear1 = nn.Linear(d_model, d_ff * 2)  # *2 for GLU
        self.linear2 = nn.Linear(d_ff, d_model)
        self.dropout = nn.Dropout(dropout)

        self.activation = activation

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # GLU activation
        x = self.linear1(x)
        x, gate = x.chunk(2, dim=-1)

        if self.activation == "gelu":
            x = F.gelu(x) * torch.sigmoid(gate)
        else:
            x = F.relu(x) * torch.sigmoid(gate)

        x = self.dropout(x)
        x = self.linear2(x)
        x = self.dropout(x)

        return x


class TransformerBlock(nn.Module):
    """transformer block with pre-norm and modifications"""

    def __init__(
        self,
        d_model: int,
        nhead: int,
        d_ff: int,
        dropout: float = 0.1,
        use_relative_position: bool = True,
    ):
        super().__init__()

        # Multi-head attention
        self.attention = MultiHeadAttention(
            d_model, nhead, dropout, use_relative_position
        )

        # Feed-forward network
        self.feed_forward = FeedForwardNetwork(d_model, d_ff, dropout)

        # Layer normalization
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)

        # Dropout
        self.dropout = nn.Dropout(dropout)

    def forward(
        self, x: torch.Tensor, mask: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        # Pre-norm architecture with residual connections
        # Attention block
        residual = x
        x = self.norm1(x)
        x = self.attention(x, x, x, mask)
        x = self.dropout(x) + residual

        # Feed-forward block
        residual = x
        x = self.norm2(x)
        x = self.feed_forward(x)
        x = self.dropout(x) + residual

        return x
