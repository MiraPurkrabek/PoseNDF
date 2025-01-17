"""Sample poses from manifold"""

import argparse
from configs.config import load_config
# General config

#from model_quat import  train_manifold2 as train_manifold
from model.posendf import PoseNDF
import shutil
from data.data_splits import amass_splits
import ipdb
import torch
import numpy as np
from body_model import BodyModel
from exp_utils import renderer

from pytorch3d.transforms import axis_angle_to_quaternion, axis_angle_to_matrix, matrix_to_quaternion, quaternion_to_axis_angle
from tqdm import tqdm
from pytorch3d.io import save_obj
import os

from torch.autograd import grad


def gradient(inputs, outputs):
    d_points = torch.ones_like(outputs, requires_grad=False, device=outputs.device)
    points_grad = grad(
        outputs=outputs,
        inputs=inputs,
        grad_outputs=d_points,
        create_graph=True,
        retain_graph=True,
        only_inputs=True)[0]
    return points_grad


class SamplePose(object):
    def __init__(self, posendf,  body_model, out_path='./experiment_results/sample_pose', debug=False, device='cuda:0', batch_size=1, gender='male'):
        self.debug = debug
        self.device = device
        self.pose_prior = posendf
        self.body_model = body_model
        self.out_path = out_path
        self.betas = torch.zeros((batch_size,10)).to(device=self.device)  #for visualization
    
    @staticmethod
    def visualize(vertices, faces, out_path, device, joints=None, render=False, prefix='out', save_mesh=False):
        # save meshes and rendered results if needed
        os.makedirs(out_path,exist_ok=True)
        if save_mesh:
            os.makedirs( os.path.join(out_path, 'meshes'), exist_ok=True)
            [save_obj(os.path.join(out_path, 'meshes', '{}_{:04}.obj'.format(prefix,i) ), vertices[i], faces) for i in range(len(vertices))]

        if render:
            renderer(vertices, faces, out_path, device=device,  prefix=prefix)
        
    def project(self, noisy_poses, gt_poses=None,  iterations=10, steps_per_iter=50):
        # create initial SMPL joints and vertices for visualition(to be used for data term)
        noise_pose_aa = torch.zeros((len(noisy_poses), 23, 3)).to(device=self.device)
        noise_pose_aa[:, :21] = quaternion_to_axis_angle(noisy_poses)
        smpl_init = self.body_model(betas=self.betas, pose_body=noise_pose_aa.view(-1, 69)) 
        self.visualize(smpl_init.vertices, smpl_init.faces, self.out_path, device=self.device, joints=smpl_init.Jtr, render=True, prefix='init')

        init_verts = smpl_init.vertices.detach().cpu().numpy()
        pose_init = noise_pose_aa.detach().cpu().numpy()
        # Optimizer
        noisy_poses.requires_grad = True
        
        # Get loss_weights
        for it in range(10):
            net_pred = self.pose_prior(noisy_poses, train=False)
            print(torch.mean(net_pred['dist_pred']))
            grad = gradient(noisy_poses, net_pred['dist_pred']).reshape(-1, 84)
            noisy_poses = noisy_poses - (net_pred['dist_pred']*grad).reshape(-1, 21,4)
        # ipdb.set_trace()

        # ipdb.set_trace()
        # create final results
        noise_pose_aa = torch.zeros((len(noisy_poses), 23, 3)).to(device=self.device)
        noise_pose_aa[:, :21] = quaternion_to_axis_angle(noisy_poses)
        smpl_init = self.body_model(betas=self.betas, pose_body=noise_pose_aa.view(-1, 69)) 
        self.visualize(smpl_init.vertices, smpl_init.faces, self.out_path, device=self.device, joints=smpl_init.Jtr, render=True,prefix='out')
        # ipdb.set_trace()


def sample_pose(opt, ckpt, motion_file=None,gt_data=None, out_path=None):
    ### load the model
    net = PoseNDF(opt)
    device= 'cuda:0'
    ckpt = torch.load(ckpt, map_location='cpu')['model_state_dict']
    net.load_state_dict(ckpt)
    net.eval()
    net = net.to(device)
    batch_size= 10
    #if noisy pose path not given, then generate random quaternions
    noisy_pose = torch.rand((batch_size,21,4))
    noisy_pose = torch.nn.functional.normalize(noisy_pose,dim=2).to(device=device)

    #  load body model
    bm_dir_path = 'models/smpl'
    body_model = BodyModel(bm_path=bm_dir_path, model_type='smpl', batch_size=batch_size,  num_betas=10).to(device=device)

    # create Motion denoiser layer
    pose_sampler = SamplePose(net, body_model=body_model, batch_size=batch_size, out_path=out_path)
    pose_sampler.project(noisy_pose)




if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Interpolate using PoseNDF.'
    )
    parser.add_argument('--config', '-c', default='models/config.yaml', type=str, help='Path to config file.')
    parser.add_argument('--ckpt_path', '-ckpt', default='models/checkpoint_epoch_best.tar', type=str, help='Path to pretrained model.')
    parser.add_argument('--noisy_pose', '-np', default='/BS/humanpose/static00/data/PoseNDF_exp/motion_denoise_data/SSM_synced/20161014_50033/punch_kick_sync_poses.npz', type=str, help='Path to noisy motion file')
    parser.add_argument('--outpath_folder', '-out', default='output/sampled_poses', type=str, help='Path to output')
    args = parser.parse_args()

    opt = load_config(args.config)

    sample_pose(opt, args.ckpt_path, out_path=args.outpath_folder)
