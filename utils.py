import csv
import os
import sys

from torch.nn.functional import log_softmax
from torch.nn import CrossEntropyLoss
from matplotlib import pyplot as plt
from torch.utils.data import SubsetRandomSampler, DataLoader
from torch import no_grad, log_softmax
from torch import max as torch_max
import numpy as np
from PIL import Image
import torchvision
import pandas as pd

from models.ViT_model import ViT
from models.hybrid_ViT_model import ResnetHybridViT
from dataset import OxfordPetsDataset, OxfordFlowersDataset
from dataset import LoadTorchData

def get_ViT_name(model_type, patch_size=16, hybrid=False, backbone_name="resnet50"):
    if hybrid:
        #model_name = backbone_name+"+"+str(model_type)+"_"+str(patch_size)
        model_name = backbone_name+"+"+str(model_type)
    else:
        model_name = str(model_type)+"_"+str(patch_size)
    return model_name

def get_ViT_model(type, image_size, patch_size, n_classes, n_channels, dropout, hybrid, backbone_name):
    assert type == "ViT-XS" or type == "ViT-S" or type == "ViT-B", \
        "ViT type error: type permitted are 'ViT-XS', 'ViT-S', 'ViT-B'"
    if type == "ViT-XS":
        emb_dim, n_heads, depth, mlp_size = 64, 4, 6, 128
    elif type == "ViT-S":
        emb_dim, n_heads, depth, mlp_size = 256, 8, 8, 512
    elif type == "ViT-B":
        emb_dim, n_heads, depth, mlp_size = 768, 12, 12, 3072
    if hybrid:
        model = ResnetHybridViT(image_size=image_size, num_classes=n_classes,
                    dim=emb_dim, depth=depth, num_heads=n_heads,
                    feedforward_dim=mlp_size, dropout=dropout, backbone=backbone_name,
                    downsample_ratio=patch_size, channels=n_channels)
    else:
        model = ViT(image_size=image_size, patch_size=patch_size, num_classes=n_classes,
                   channels=n_channels, dim=emb_dim, depth=depth, num_heads=n_heads,
                   feedforward_dim=mlp_size, dropout=dropout)
    return model

def get_resnet_model(resnet_type, n_classes):
    assert resnet_type == "resnet18" or resnet_type == "resnet34" or resnet_type == "resnet50" or resnet_type == "resnet101" \
           or resnet_type == "resnet152", "resnet type error"
    if resnet_type == "resnet18":
        model = torchvision.models.resnet18(pretrained=False, num_classes=n_classes)
    elif resnet_type == "resnet34":
        model = torchvision.models.resnet34(pretrained=False, num_classes=n_classes)
    elif resnet_type == "resnet50":
        model = torchvision.models.resnet50(pretrained=False, num_classes=n_classes)
    elif resnet_type == "resnet101":
        model = torchvision.models.resnet101(pretrained=False, num_classes=n_classes)
    elif resnet_type == "resnet152":
        model = torchvision.models.resnet152(pretrained=False, num_classes=n_classes)
    return model

def get_output_path(root_path, model_name, data_augmentation, dataset_name):
    root_path = os.path.join(root_path, dataset_name, model_name)
    if data_augmentation:
        root_path = os.path.join(root_path, "augmentation")
    else:
        root_path = os.path.join(root_path, "no_augmentation")
    graph_path = os.path.join(root_path, "graph")
    model_path = os.path.join(root_path, "pretrained_models")
    if not os.path.exists(model_path):
        os.makedirs(model_path)
    if not os.path.exists(graph_path):
        os.makedirs(graph_path)
    model_path = os.path.join(model_path, model_name+".pth")
    return graph_path, model_path

def get_transforms(augmentation, image_size):
    if augmentation:
        transforms = {
            'train': torchvision.transforms.Compose([
                torchvision.transforms.Resize(int(int(image_size)), Image.BICUBIC),
                torchvision.transforms.RandomCrop(image_size, padding=4),
                torchvision.transforms.RandomHorizontalFlip(),
                torchvision.transforms.ToTensor(),
                torchvision.transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
            ]),
            'val': torchvision.transforms.Compose([
                torchvision.transforms.Resize(int(int(image_size)), Image.BICUBIC),
                torchvision.transforms.RandomCrop(image_size, padding=4),
                torchvision.transforms.RandomHorizontalFlip(),
                torchvision.transforms.ToTensor(),
                torchvision.transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
            ]),
        }
    else:
        transforms = {
            'train': torchvision.transforms.Compose([
                torchvision.transforms.Resize(int(int(image_size)), Image.BICUBIC),
                torchvision.transforms.ToTensor(),
                torchvision.transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
            ]),
            'val': torchvision.transforms.Compose([
                torchvision.transforms.Resize(int(int(image_size)), Image.BICUBIC),
                torchvision.transforms.ToTensor(),
                torchvision.transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
            ]),
        }
    transforms['test'] = torchvision.transforms.Compose([
                torchvision.transforms.Resize(int(int(image_size)), Image.BICUBIC),
                torchvision.transforms.ToTensor(),
                torchvision.transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010))
            ])
    return transforms

def get_loader_from_dataset(dataset_name, root_path, image_size, batch_size_train=128, batch_size_test=128,
                              augmentation=True, val_ratio=0.2, n_cpu=8):
    assert dataset_name == "oxfordpets" or dataset_name == "oxfordflowers" or dataset_name == "CIFAR-10" \
           or dataset_name == "CIFAR-100",\
        "custom dataset name error: you can actually select oxfordpets, oxfordflowers, CIFAR-10 or CIFAR-100"
    train_loader, val_loader, test_loader = None, None, None
    transforms = get_transforms(augmentation=augmentation, image_size=image_size)
    dataset_path = os.path.join(root_path, dataset_name)
    if dataset_name == "oxfordpets":
        trainval_dataset = OxfordPetsDataset(dataset_path=dataset_path, mode="train",
                                             transforms=transforms["train"])
        test_dataset = OxfordPetsDataset(dataset_path=dataset_path, mode="test",
                                            transforms=transforms["test"])
        train_loader, val_loader, test_loader = get_loader_splitting_val(train_dataset=trainval_dataset,
                                        test_dataset=test_dataset, batch_size_train=batch_size_train,
                                        batch_size_test=batch_size_test, n_cpu=n_cpu, val_ratio=val_ratio)
    elif dataset_name == "oxfordflowers":
        train_dataset = OxfordFlowersDataset(dataset_path=dataset_path, mode="train",
                                             transforms=transforms["train"])
        val_dataset = OxfordFlowersDataset(dataset_path=dataset_path, mode="val",
                                             transforms=transforms["val"])
        test_dataset = OxfordFlowersDataset(dataset_path=dataset_path, mode="test",
                                            transforms=transforms["test"])
        train_loader = DataLoader(train_dataset, batch_size=batch_size_train,num_workers=n_cpu)
        val_loader = DataLoader(val_dataset, batch_size=batch_size_train, num_workers=n_cpu)
        test_loader = DataLoader(test_dataset, batch_size=batch_size_test, shuffle=True, num_workers=n_cpu)
    elif dataset_name == "CIFAR-10" or dataset_name == "CIFAR-100":
        return LoadTorchData(root_path=dataset_path, download=True).load_dataset(dataset_name, batch_size_train,
                                                                                  batch_size_test, val_ratio, n_cpu,
                                                                                  transforms)
    return train_loader, val_loader, test_loader

def get_loader_splitting_val(train_dataset, test_dataset, batch_size_train, batch_size_test, n_cpu, val_ratio):
    dataset_len = len(train_dataset)
    indices = list(range(dataset_len))
    val_len = int(np.floor(val_ratio * dataset_len))
    validation_idx = np.random.choice(indices, size=val_len, replace=False)
    train_idx = list(set(indices) - set(validation_idx))
    train_sampler = SubsetRandomSampler(train_idx)
    validation_sampler = SubsetRandomSampler(validation_idx)

    train_loader = DataLoader(train_dataset, batch_size=batch_size_train, sampler=train_sampler,
                                               num_workers=n_cpu)
    validation_loader = DataLoader(train_dataset, batch_size=batch_size_train,
                                                    sampler=validation_sampler,
                                                    num_workers=n_cpu)
    test_loader = DataLoader(test_dataset, batch_size=batch_size_test, shuffle=True,num_workers=n_cpu)
    return train_loader, validation_loader, test_loader

def evaluate(model, data_loader, device, acc_history=[], loss_history=[], mode="test"):
    model.eval()
    total_samples = len(data_loader.sampler)
    num_batch = len(data_loader)
    correct_samples = 0
    total_loss = 0
    criterion = CrossEntropyLoss()
    with no_grad():
        for data, target in data_loader:
            data = data.to(device)
            target = target.to(device)
            output = log_softmax(model(data), dim=1)
            loss = criterion(output, target)
            _, pred = torch_max(output, dim=1)
            total_loss += loss.item()
            correct_samples += pred.eq(target).sum()
    avg_loss = total_loss / num_batch
    accuracy = 100.0 * correct_samples / total_samples
    if mode == "validation":
        loss_history.append(avg_loss)
        acc_history.append(accuracy)
        sys.stdout.write(' %s: %.4f -- %s: %.2f \n' % ("val_loss",  avg_loss, "val_acc",  accuracy))
    return avg_loss, accuracy


def read_csv_from_path(file_path):
    data = {}
    with open(file_path, 'r') as data_file:
        reader = csv.reader(data_file)
        for idx, row in enumerate(reader):
            if idx > 0:
                dataset = row[0]
                model = row[1]

                if model not in data.keys():
                    data[model] = {}
                data[model][dataset] = {'#epochs': row[2], 'batch_size': row[3], 'lr': row[4], 'optimizer': row[5],
                                        'dropout': row[6], 'test_loss': row[7], 'test_acc': row[8], 'epoch': row[9],
                                        'best_time': row[10], 'exec_time': row[11]}
    return data

def write_on_csv(data, out_df, csv_path):
    for dataset in data.keys():
        for model in data[dataset].keys():
            data_to_add = [dataset, model, data[model][dataset]["#epochs"],  data[model][dataset]["batch_size"],
                           data[model][dataset]["lr"], data[model][dataset]["optimizer"],
                           data[model][dataset]["dropout"], data[model][dataset]["test_loss"],
                           data[model][dataset]["test_acc"], data[model][dataset]["epoch"],
                           data[model][dataset]["best_time"], data[model][dataset]["exec_time"]]
            data_df_scores = np.hstack((np.array(data_to_add).reshape(1, -1)))
            out_df = out_df.append(pd.Series(data_df_scores.reshape(-1), index=out_df.columns),
                                   ignore_index=True)
    out_df.to_csv(csv_path, index=False, header=True)

def get_time_in_format(millisecond):
    hours, rem = divmod(millisecond, 3600)
    minutes, seconds = divmod(rem, 60)
    return "{:0>2}:{:0>2}:{:05.2f}".format(int(hours), int(minutes), seconds)

def save_result_on_csv(csv_path, model_name, dataset_name, batch_size,
                       lr, n_epochs, execution_time, optimizer, dropout, overwrite=False, best_test_loss=0, best_test_acc=0, best_epoch=0,
                       best_time=0):
    data = {}
    if not overwrite and os.path.isfile(csv_path):
        data = read_csv_from_path(csv_path)
    out_df_scores = pd.DataFrame(columns=['dataset', 'model', '#epochs', 'batch_size', 'lr', 'optimizer', 'dropout',
                                          'test_loss', 'test_acc(%)', 'epoch', 'best_time(h)', 'training_time(h)'])
    if dataset_name not in data.keys():
        data[dataset_name] = {}
    execution_time = get_time_in_format(execution_time)
    best_time = get_time_in_format(best_time)
    data[dataset_name][model_name] = {'#epochs': str(n_epochs), 'batch_size': str(batch_size), 'lr': str(lr),
                                      'optimizer': optimizer, 'dropout': str(dropout),
                                      'test_loss': str( '{:.4f}'.format(best_test_loss)),
                                      'test_acc': '{:4.2f}'.format(best_test_acc), 'epoch': str(best_epoch),
                                       'best_time': best_time, 'exec_time': execution_time}
    write_on_csv(data, out_df_scores, csv_path)

def train_epoch(model, optimizer, train_loader, loss_history, acc_history, device, epoch, n_epochs):
    total_samples = len(train_loader.dataset)
    num_batch = len(train_loader)
    model.train()
    sum_losses = 0
    total_correct_samples = 0
    criterion = CrossEntropyLoss()
    for i, (data, target) in enumerate(train_loader):
        data = data.to(device)
        target = target.to(device)
        optimizer.zero_grad()
        output = log_softmax(model(data), dim=1)
        loss = criterion(output, target)
        _, pred = torch_max(output, dim=1)
        correct_samples = pred.eq(target).sum()
        accuracy = 100.0 * correct_samples / len(data)
        total_correct_samples += correct_samples
        sum_losses += loss.item()
        loss.backward()
        optimizer.step()
        sys.stdout.write('\rEpoch %03d/%03d [%03d/%03d] -- %s: %.4f -- %s: %.2f --' % (epoch, n_epochs, i+1,
                                                                    num_batch, "train_loss",  loss.item(),
                                                                    "train_acc",  accuracy))
    loss_history.append(sum_losses/num_batch)
    acc_history.append(100.0 * total_correct_samples / total_samples)

def update_graph(train_loss_history, val_loss_history, train_acc_history, val_acc_history, path):
    losses_img_file = os.path.join(path, "pre_training_losses.png")
    acc_img_file = os.path.join(path, "pre_training_accuracy.png")
    epochs = np.arange(1, len(train_loss_history)+1)
    plt.xlabel("epoch")
    plt.ylabel("loss")
    plt.title("Plot Training/Validation Losses")
    plt.ylim(0, max(max(train_loss_history), max(val_loss_history)))
    plt.plot(epochs, train_loss_history, label="average train loss")
    plt.plot(epochs, val_loss_history, label="average validation loss")
    plt.legend()
    plt.savefig(losses_img_file)
    plt.close()
    plt.title("Plot Validation Accuracy")
    plt.xlabel("epoch")
    plt.ylabel("accuracy(%)")
    plt.ylim(0, 100)
    plt.plot(epochs, train_acc_history, label="average train accuracy")
    plt.plot(epochs, val_acc_history, label="average validation accuracy")
    plt.legend()
    plt.savefig(acc_img_file)
    plt.close()

class LambdaLR():
    def __init__(self, n_epochs, offset, decay_start_epoch):
        assert ((n_epochs - decay_start_epoch) > 0), "Decay must start before the training session ends!"
        self.n_epochs = n_epochs
        self.offset = offset
        self.decay_start_epoch = decay_start_epoch

    def step(self, epoch):
        return 1.0 - max(0, epoch + self.offset - self.decay_start_epoch)/(self.n_epochs - self.decay_start_epoch)