"""LSTM sequence autoencoder; reconstruction errors are not probabilities."""

import torch
from torch import Tensor, nn


class LSTMAutoencoder(nn.Module):
    """Compress one flow channel to a latent vector and reconstruct the sequence."""

    def __init__(self, hidden_size: int = 32, latent_size: int = 8):
        super().__init__()
        if any(type(size) is not int or size < 1 for size in (hidden_size, latent_size)):
            raise ValueError("Model dimensions must be positive integers")
        self.encoder = nn.LSTM(1, hidden_size, batch_first=True)
        self.to_latent = nn.Linear(hidden_size, latent_size)
        self.decoder = nn.LSTM(latent_size, hidden_size, batch_first=True)
        self.to_flow = nn.Linear(hidden_size, 1)

    def forward(self, flows: Tensor) -> Tensor:
        """Accept normalized float32 [batch, time, 1] values, including negatives."""
        if flows.ndim != 3 or flows.shape[0] < 1 or flows.shape[1] < 1 or flows.shape[2] != 1:
            raise ValueError("Expected nonempty [batch, time, 1] flow sequences")
        if flows.dtype != torch.float32 or not torch.isfinite(flows).all():
            raise ValueError("Flows must be finite float32 values")
        _, (hidden, _) = self.encoder(flows)
        latent = self.to_latent(hidden[-1])
        # Decoder sees only the bottleneck, never the original flow observations.
        repeated = latent.unsqueeze(1).expand(-1, flows.shape[1], -1)
        decoded, _ = self.decoder(repeated)
        return self.to_flow(decoded)


def reconstruction_errors(flows: Tensor, reconstructed: Tensor) -> tuple[Tensor, Tensor]:
    """Return squared error per interval and its mean per window, in normalized units."""
    if (flows.shape != reconstructed.shape or flows.ndim != 3 or
            flows.shape[0] < 1 or flows.shape[1] < 1 or flows.shape[2] != 1):
        raise ValueError("Expected matching nonempty [batch, time, 1] tensors")
    if (flows.dtype != torch.float32 or reconstructed.dtype != torch.float32 or
            not torch.isfinite(flows).all() or not torch.isfinite(reconstructed).all()):
        raise ValueError("Inputs must be finite float32 values")
    intervals = (flows - reconstructed).square().squeeze(-1)
    return intervals, intervals.mean(dim=1)
