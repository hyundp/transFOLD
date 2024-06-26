import os
import random
import time
import pickle
import torch
import numpy as np
import matplotlib.pyplot as plt
from torch.utils.data import Dataset
from transformer.gpt_transformer.src.data.d4rl_infos import REF_MIN_SCORE, REF_MAX_SCORE, D4RL_DATASET_STATS


def make_dir(path):
    try:
        if not os.path.exists(path):
            os.makedirs(path)
    except OSError:
        print("Error: Failed to create the directory.")
        
def check_batch(batch_size, val_length):
    new_batch_size = batch_size
    while (val_length < new_batch_size):
        new_batch_size //= 2
    
    return new_batch_size

def discount_cumsum(x, gamma):
    disc_cumsum = np.zeros_like(x)
    disc_cumsum[-1] = x[-1]
    for t in reversed(range(x.shape[0]-1)):
        disc_cumsum[t] = x[t] + gamma * disc_cumsum[t+1]
    return disc_cumsum


def get_d4rl_normalized_score(score, env_name):
    env_key = env_name.split('-')[0].lower()
    assert env_key in REF_MAX_SCORE, f'no reference score for {env_key} env to calculate d4rl score'
    return (score - REF_MIN_SCORE[env_key]) / (REF_MAX_SCORE[env_key] - REF_MIN_SCORE[env_key])


def get_d4rl_dataset_stats(env_d4rl_name):
    return D4RL_DATASET_STATS[env_d4rl_name]

class D4RLTrajectoryDataset(Dataset):
    def __init__(self, dataset_path, context_len, val=False, val_dataset_path=None, not_path = False):

        self.context_len = context_len

        # load dataset
        if val:
            with open(val_dataset_path, 'rb') as f:
                self.trajectories = pickle.load(f)
        elif not_path:    
            self.trajectories = dataset_path
        else:
            with open(dataset_path, 'rb') as f:
                self.trajectories = pickle.load(f)

        # calculate min len of traj, state mean and variance
        
        if not not_path:
            states, next_states, rewards = [], [], []
            for traj in self.trajectories:
                # print(traj)
                states.append(traj['observations'])
                next_states.append(traj['next_observations'])
                rewards.append(traj['rewards'])
                # # calculate returns to go and rescale them
                # traj['returns_to_go'] = discount_cumsum(traj['rewards'], 1.0) / rtg_scale
            
            # used for input, output normalization
            states = np.concatenate(states, axis=0)
            # print("state shape: ", states.shape)
            self.state_mean, self.state_std = np.mean(states, axis=0), np.std(states, axis=0) + 1e-6
            
            next_states = np.concatenate(next_states, axis=0)
            self.next_state_mean, self.next_state_std = np.mean(next_states, axis=0), np.std(next_states, axis=0) + 1e-6
            
            rewards = np.concatenate(rewards, axis=0)
            self.reward_mean, self.reward_std = np.mean(rewards, axis=0), np.std(rewards, axis=0) + 1e-6

            # normalize states, next_states, rewards
            for traj in self.trajectories:
                traj['observations'] = (traj['observations'] - self.state_mean) / self.state_std
                traj['next_observations'] = (traj['next_observations'] - self.next_state_mean) / self.next_state_std
                traj['rewards'] = (traj['rewards'] - self.reward_mean) / self.reward_std

    def get_state_stats(self):
        return self.state_mean, self.state_std

    def __len__(self):
        return len(self.trajectories)

    def __getitem__(self, idx):
        traj = self.trajectories[idx]
        traj_len = traj['observations'].shape[0]

        if traj_len >= self.context_len:
            # sample random index to slice trajectory
            si = random.randint(0, traj_len - self.context_len)

            states = torch.from_numpy(traj['observations'][si : si + self.context_len])
            actions = torch.from_numpy(traj['actions'][si : si + self.context_len])
            rewards = torch.from_numpy(traj['rewards'][si : si + self.context_len])
            next_states = torch.from_numpy(traj['next_observations'][si : si + self.context_len])
            terminals = torch.from_numpy(traj['terminals'][si : si + self.context_len])
            timesteps = torch.arange(start=si, end=si+self.context_len, step=1)

            # all ones since no padding
            traj_mask = torch.ones(self.context_len, dtype=torch.long)

        else:
            padding_len = self.context_len - traj_len

            # padding with zeros
            states = torch.from_numpy(traj['observations'])
            states = torch.cat([states,
                                torch.zeros(([padding_len] + list(states.shape[1:])),
                                dtype=states.dtype)],
                               dim=0)
    
            next_states = torch.from_numpy(traj['next_observations'])
            next_states = torch.cat([next_states,
                                torch.zeros(([padding_len] + list(next_states.shape[1:])),
                                dtype=next_states.dtype)],
                               dim=0)                           
                            

            actions = torch.from_numpy(traj['actions'])
            actions = torch.cat([actions,
                                torch.zeros(([padding_len] + list(actions.shape[1:])),
                                dtype=actions.dtype)],
                               dim=0)

            rewards = torch.from_numpy(traj['rewards'])
            rewards = torch.cat([rewards,
                                torch.zeros(([padding_len] + list(rewards.shape[1:])),
                                dtype=rewards.dtype)],
                               dim=0)

            terminals = torch.from_numpy(traj['terminals'])
            terminals = torch.cat([terminals,
                                torch.zeros(([padding_len] + list(terminals.shape[1:])),
                                dtype=terminals.dtype)],
                               dim=0)

            timesteps = torch.arange(start=0, end=self.context_len, step=1)

            traj_mask = torch.cat([torch.ones(traj_len, dtype=torch.long),
                                   torch.zeros(padding_len, dtype=torch.long)],
                                  dim=0)

        return  timesteps, states, next_states, actions, rewards, traj_mask, terminals
