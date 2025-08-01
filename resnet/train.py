import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pandas as pd
import os
from sklearn.metrics import mean_squared_error, r2_score
from dataset import get_dataloaders, get_raw_split
from prepare_data import load_and_augment_labels
from model import ResNet_Model
import config

# Set device to CUDA if available, otherwise CPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def predict_in_batches(model, images, batch_size):
    """
    Perform model predictions in batches to avoid memory overflow.

    Args:
        model (nn.Module): Trained PyTorch model.
        images (torch.Tensor): Tensor of input images.
        batch_size (int): Number of images per batch.

    Returns:
        np.ndarray: Concatenated predictions as a NumPy array.
    """
    model.eval()
    preds = []

    with torch.no_grad():
        for i in range(0, images.shape[0], batch_size):
            batch = images[i:i+batch_size].to(device)
            pred = model(batch)
            preds.append(pred.cpu().numpy())

    return np.vstack(preds)


def train():
    """
    Main training loop for the regression model.

    Workflow:
        1. Load training/testing data and normalization stats.
        2. Initialize model, loss, optimizer.
        3. Train the model for defined epochs.
        4. Log evaluation metrics every 5 epochs.
        5. Save predictions vs actual values to Excel.
        6. Save trained model and normalization stats.
    """
    print(f"Using device: {device}")

    # 1. Load dataset and full image/label splits
    train_loader, test_loader = get_dataloaders()
    train_images, train_labels, test_images, test_labels, mean_val, std_val = get_raw_split()

    # 2. Initialize model, loss function (MSE), and optimizer (Adam)
    model = ResNet_Model().to(device)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=config.lr)

    # 3. Training loop
    for epoch in range(config.num_epochs):
        model.train()
        for x_batch, y_batch in train_loader:
            x_batch, y_batch = x_batch.to(device), y_batch.to(device)

            optimizer.zero_grad()
            loss = criterion(model(x_batch), y_batch)
            loss.backward()
            optimizer.step()

        # Every 5 epochs (or final epoch), evaluate and log metrics
        if epoch % 5 == 0 or epoch == config.num_epochs - 1:
            train_preds = predict_in_batches(model, train_images, config.train_batch_size)
            test_preds = predict_in_batches(model, test_images, config.test_batch_size)

            train_rmse = np.sqrt(mean_squared_error(train_labels.cpu(), train_preds))
            test_rmse = np.sqrt(mean_squared_error(test_labels.cpu(), test_preds))
            train_r2 = r2_score(train_labels.cpu(), train_preds)
            test_r2 = r2_score(test_labels.cpu(), test_preds)

            print(f"[{epoch}] Train RMSE: {train_rmse:.2f}, Test RMSE: {test_rmse:.2f}, "
                  f"Train R²: {train_r2:.2f}, Test R²: {test_r2:.2f}")

    # 4. Denormalize predictions and labels
    std_val = std_val.item() if hasattr(std_val, 'item') else float(std_val)
    mean_val = mean_val.item() if hasattr(mean_val, 'item') else float(mean_val)

    train_preds_actual = train_preds * std_val + mean_val
    test_preds_actual = test_preds * std_val + mean_val
    train_true_actual = train_labels.cpu().numpy() * std_val + mean_val
    test_true_actual = test_labels.cpu().numpy() * std_val + mean_val

    # 5. Save predictions vs ground truth to Excel
    target = config.target_col
    excel_output = f"predictions_vs_actual_col{target}.xlsx"

    with pd.ExcelWriter(excel_output) as writer:
        pd.DataFrame({
            "True": train_true_actual.flatten(),
            "Predicted": train_preds_actual.flatten()
        }).to_excel(writer, sheet_name="Train", index=False)

        pd.DataFrame({
            "True": test_true_actual.flatten(),
            "Predicted": test_preds_actual.flatten()
        }).to_excel(writer, sheet_name="Test", index=False)

    # 6. Save model checkpoint and normalization parameters
    os.makedirs(config.model_dir, exist_ok=True)
    model_save_path = os.path.join(config.model_dir, f"model{target}.pth")
    torch.save({
        'model_state_dict': model.state_dict(),
        'mean': mean_val,
        'std': std_val
    }, model_save_path)

    print(f"Model and normalization params saved to: {model_save_path}")


if __name__ == "__main__":
    train()
