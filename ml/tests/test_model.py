import io
import unittest

import torch

from aquamind_ml.model import LSTMAutoencoder, reconstruction_errors


class ModelTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(42)
        self.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        self.addCleanup(torch.set_num_threads, self.previous_threads)
        self.model = LSTMAutoencoder(hidden_size=8, latent_size=3)

    def test_shape_gradients_and_batch_independence(self):
        flows = torch.randn(3, 96, 1)
        reconstructed = self.model(flows)
        self.assertEqual(reconstructed.shape, flows.shape)
        torch.testing.assert_close(reconstructed[:1], self.model(flows[:1]))
        reconstructed.square().mean().backward()
        for name, parameter in self.model.named_parameters():
            self.assertIsNotNone(parameter.grad, name)
            self.assertTrue(torch.isfinite(parameter.grad).all(), name)
            self.assertGreater(parameter.grad.abs().sum().item(), 0, name)

    def test_error_values_and_backpropagation(self):
        flows = torch.tensor([[[1.0], [3.0]], [[2.0], [4.0]]])
        output = torch.zeros_like(flows, requires_grad=True)
        intervals, windows = reconstruction_errors(flows, output)
        torch.testing.assert_close(intervals, torch.tensor([[1.0, 9.0], [4.0, 16.0]]))
        torch.testing.assert_close(windows, torch.tensor([5.0, 10.0]))
        windows.mean().backward()
        self.assertIsNotNone(output.grad)

    def test_optimizer_can_learn_a_simple_sequence(self):
        # A learning smoke test, not held-out leak-detection evidence.
        flows = torch.ones(4, 12, 1) * 0.5
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.02)
        initial = (self.model(flows) - flows).square().mean().item()
        for _ in range(60):
            optimizer.zero_grad()
            loss = (self.model(flows) - flows).square().mean()
            loss.backward()
            optimizer.step()
        final = (self.model(flows) - flows).square().mean().item()
        self.assertLess(final, initial * 0.1)

    def test_weight_round_trip_preserves_predictions(self):
        flows = torch.randn(2, 96, 1)
        buffer = io.BytesIO()
        torch.save(self.model.state_dict(), buffer)
        buffer.seek(0)
        restored = LSTMAutoencoder(hidden_size=8, latent_size=3)
        restored.load_state_dict(torch.load(buffer, weights_only=True))
        torch.testing.assert_close(restored(flows), self.model(flows), rtol=0, atol=0)

    def test_rejects_invalid_inputs(self):
        for flows in (torch.ones(96), torch.ones(2, 96, 2), torch.ones(0, 96, 1),
                      torch.ones(2, 0, 1), torch.ones(2, 96, 1, dtype=torch.int64),
                      torch.full((2, 96, 1), float("nan"))):
            with self.subTest(shape=flows.shape, dtype=flows.dtype):
                with self.assertRaises(ValueError):
                    self.model(flows)
        with self.assertRaises(ValueError):
            reconstruction_errors(torch.ones(2, 96, 1), torch.ones(1, 96, 1))
        for size in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                LSTMAutoencoder(hidden_size=size)


if __name__ == "__main__":
    unittest.main()
