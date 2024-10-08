# coding: utf-8
__author__ = 'Roman Solovyev (ZFTurbo): https://github.com/ZFTurbo/'

import argparse
import time
from tqdm import tqdm
import sys
import os
import glob
import copy
import torch
import soundfile as sf
import numpy as np
import torch.nn as nn
import multiprocessing

import warnings
warnings.filterwarnings("ignore")

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from utils import demix, sdr, get_model_from_config

import logging
log_format = "%(asctime)s.%(msecs)03d [%(levelname)s] %(module)s - %(message)s"
date_format = "%H:%M:%S"
logging.basicConfig(level = logging.INFO, format = log_format, datefmt = date_format)
logger = logging.getLogger(__name__)

def proc_list_of_files(
    mixture_paths,
    model,
    args,
    config,
    device,
    verbose=False,
    is_tqdm=True
):
    instruments = config.training.instruments
    if config.training.target_instrument is not None:
        instruments = [config.training.target_instrument]

    if args.store_dir != "":
        if not os.path.isdir(args.store_dir):
            os.mkdir(args.store_dir)

    all_sdr = dict()
    for instr in config.training.instruments:
        all_sdr[instr] = []

    if is_tqdm:
        mixture_paths = tqdm(mixture_paths)

    for path in mixture_paths:
        start_time = time.time()
        mix, sr = sf.read(path)
        mix_orig = mix.copy()

        # Fix for mono
        if len(mix.shape) == 1:
            mix = np.expand_dims(mix, axis=-1)

        mix = mix.T # (channels, waveform)
        folder = os.path.dirname(path)
        folder_name = os.path.abspath(folder)
        if verbose:
            logger.info('Song: {}'.format(folder_name))

        if 'normalize' in config.inference:
            if config.inference['normalize'] is True:
                mono = mix.mean(0)
                mean = mono.mean()
                std = mono.std()
                mix = (mix - mean) / std

        if args.use_tta:
            # orig, channel inverse, polarity inverse
            track_proc_list = [mix.copy(), mix[::-1].copy(), -1. * mix.copy()]
        else:
            track_proc_list = [mix.copy()]

        full_result = []
        for mix in track_proc_list:
            waveforms = demix(config, model, mix, device, model_type=args.model_type)
            full_result.append(waveforms)

        # Average all values in single dict
        waveforms = full_result[0]
        for i in range(1, len(full_result)):
            d = full_result[i]
            for el in d:
                if i == 2:
                    waveforms[el] += -1.0 * d[el]
                elif i == 1:
                    waveforms[el] += d[el][::-1].copy()
                else:
                    waveforms[el] += d[el]
        for el in waveforms:
            waveforms[el] = waveforms[el] / len(full_result)

        pbar_dict = {}
        for instr in instruments:
            if instr != 'other' or config.training.other_fix is False:
                try:
                    track, sr1 = sf.read(folder + '/{}.{}'.format(instr, args.extension))

                    # Fix for mono
                    if len(track.shape) == 1:
                        track = np.expand_dims(track, axis=-1)

                except Exception as e:
                    logger.info('No data for stem: {}. Skip!'.format(instr))
                    continue
            else:
                # other is actually instrumental
                track, sr1 = sf.read(folder + '/{}.{}'.format('vocals', args.extension))
                track = mix_orig - track

            estimates = waveforms[instr].T
            # logger.info(estimates.shape)
            if 'normalize' in config.inference:
                if config.inference['normalize'] is True:
                    estimates = estimates * std + mean

            if args.store_dir != "":
                sf.write("{}/{}_{}.wav".format(args.store_dir, os.path.basename(folder), instr), estimates, sr, subtype='FLOAT')
            references = np.expand_dims(track, axis=0)
            estimates = np.expand_dims(estimates, axis=0)
            sdr_val = sdr(references, estimates)[0]
            if verbose:
                logger.info(instr, waveforms[instr].shape, sdr_val, "Time: {:.2f} sec".format(time.time() - start_time))
            all_sdr[instr].append(sdr_val)
            pbar_dict['sdr_{}'.format(instr)] = sdr_val

            try:
                mixture_paths.set_postfix(pbar_dict)
            except Exception as e:
                pass

    return all_sdr


def valid(model, args, config, device, verbose=False):
    start_time = time.time()
    model.eval().to(device)
    all_mixtures_path = glob.glob(args.valid_path + '/*/mixture.' + args.extension)
    logger.info('Total mixtures: {}'.format(len(all_mixtures_path)))
    logger.info('Overlap: {} Batch size: {}'.format(config.inference.num_overlap, config.inference.batch_size))

    all_sdr = proc_list_of_files(all_mixtures_path, model, args, config, device, verbose, not verbose)

    instruments = config.training.instruments
    if config.training.target_instrument is not None:
        instruments = [config.training.target_instrument]

    if args.store_dir != "":
        out = open(args.store_dir + '/results.txt', 'w')
        out.write(str(args) + "\n")
    logger.info("Num overlap: {}".format(config.inference.num_overlap))
    sdr_avg = 0.0
    for instr in instruments:
        npsdr = np.array(all_sdr[instr])
        sdr_val = npsdr.mean()
        sdr_std = npsdr.std()
        logger.info("Instr SDR {}: {:.4f} (Std: {:.4f})".format(instr, sdr_val, sdr_std))
        if args.store_dir != "":
            out.write("Instr SDR {}: {:.4f}".format(instr, sdr_val) + "\n")
        sdr_avg += sdr_val
    sdr_avg /= len(instruments)
    if len(instruments) > 1:
        logger.info('SDR Avg: {:.4f}'.format(sdr_avg))
    if args.store_dir != "":
        out.write('SDR Avg: {:.4f}'.format(sdr_avg) + "\n")
    logger.info("Elapsed time: {:.2f} sec".format(time.time() - start_time))
    if args.store_dir != "":
        out.write("Elapsed time: {:.2f} sec".format(time.time() - start_time) + "\n")
        out.close()

    return sdr_avg


def valid_mp(proc_id, queue, all_mixtures_path, model, args, config, device, return_dict):
    m1 = model.eval().to(device)
    if proc_id == 0:
        progress_bar = tqdm(total=len(all_mixtures_path))
    all_sdr = dict()
    for instr in config.training.instruments:
        all_sdr[instr] = []
    while True:
        current_step, path = queue.get()
        if path is None:  # check for sentinel value
            break
        sdr_single = proc_list_of_files([path], m1, args, config, device, False, False)
        pbar_dict = {}
        for instr in config.training.instruments:
            all_sdr[instr] += sdr_single[instr]
            if len(sdr_single[instr]) > 0:
                pbar_dict['sdr_{}'.format(instr)] = "{:.4f}".format(sdr_single[instr][0])
        if proc_id == 0:
            progress_bar.update(current_step - progress_bar.n)
            progress_bar.set_postfix(pbar_dict)
        # logger.info(f"Inference on process {proc_id}", all_sdr)
    return_dict[proc_id] = all_sdr
    return


def valid_multi_gpu(model, args, config, device_ids, verbose=False):
    start_time = time.time()
    all_mixtures_path = glob.glob(args.valid_path + '/*/mixture.' + args.extension)
    logger.info('Total mixtures: {}'.format(len(all_mixtures_path)))
    logger.info('Overlap: {} Batch size: {}'.format(config.inference.num_overlap, config.inference.batch_size))

    model = model.to('cpu')
    queue = torch.multiprocessing.Queue()
    processes = []
    return_dict = torch.multiprocessing.Manager().dict()
    for i, device in enumerate(device_ids):
        if torch.cuda.is_available():
            device = 'cuda:{}'.format(device)
        else:
            device = 'cpu'
        p = torch.multiprocessing.Process(target=valid_mp, args=(i, queue, all_mixtures_path, model, args, config, device, return_dict))
        p.start()
        processes.append(p)
    for i, path in enumerate(all_mixtures_path):
        queue.put((i, path))
    for _ in range(len(device_ids)):
        queue.put((None, None))  # sentinel value to signal subprocesses to exit
    for p in processes:
        p.join()  # wait for all subprocesses to finish

    all_sdr = dict()
    for instr in config.training.instruments:
        all_sdr[instr] = []
        for i in range(len(device_ids)):
            all_sdr[instr] += return_dict[i][instr]

    instruments = config.training.instruments
    if config.training.target_instrument is not None:
        instruments = [config.training.target_instrument]

    if args.store_dir != "":
        out = open(args.store_dir + '/results.txt', 'w')
        out.write(str(args) + "\n")
    logger.info("Num overlap: {}".format(config.inference.num_overlap))
    sdr_avg = 0.0
    for instr in instruments:
        npsdr = np.array(all_sdr[instr])
        sdr_val = npsdr.mean()
        sdr_std = npsdr.std()
        logger.info("Instr SDR {}: {:.4f} (Std: {:.4f})".format(instr, sdr_val, sdr_std))
        if args.store_dir != "":
            out.write("Instr SDR {}: {:.4f}".format(instr, sdr_val) + "\n")
        sdr_avg += sdr_val
    sdr_avg /= len(instruments)
    if len(instruments) > 1:
        logger.info('SDR Avg: {:.4f}'.format(sdr_avg))
    if args.store_dir != "":
        out.write('SDR Avg: {:.4f}'.format(sdr_avg) + "\n")
    logger.info("Elapsed time: {:.2f} sec".format(time.time() - start_time))
    if args.store_dir != "":
        out.write("Elapsed time: {:.2f} sec".format(time.time() - start_time) + "\n")
        out.close()

    return sdr_avg


def check_validation(args):
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_type", type=str, default='mdx23c', help="One of mdx23c, htdemucs, segm_models, mel_band_roformer, bs_roformer, swin_upernet, bandit")
    parser.add_argument("--config_path", type=str, help="path to config file")
    parser.add_argument("--start_check_point", type=str, default='', help="Initial checkpoint to valid weights")
    parser.add_argument("--valid_path", type=str, help="validate path")
    parser.add_argument("--store_dir", default="", type=str, help="path to store results as wav file")
    parser.add_argument("--device_ids", nargs='+', type=int, default=0, help='list of gpu ids')
    parser.add_argument("--num_workers", type=int, default=0, help="dataloader num_workers")
    parser.add_argument("--pin_memory", action='store_true', help="dataloader pin_memory")
    parser.add_argument("--extension", type=str, default='wav', help="Choose extension for validation")
    parser.add_argument("--use_tta", action='store_true', help="Flag adds test time augmentation during inference (polarity and channel inverse). While this triples the runtime, it reduces noise and slightly improves prediction quality.")
    if args is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(args)

    torch.backends.cudnn.benchmark = True
    torch.multiprocessing.set_start_method('spawn')

    model, config = get_model_from_config(args.model_type, args.config_path)
    if args.start_check_point != '':
        logger.info('Start from checkpoint: {}'.format(args.start_check_point))
        state_dict = torch.load(args.start_check_point)
        if args.model_type == 'htdemucs':
            # Fix for htdemucs pretrained models
            if 'state' in state_dict:
                state_dict = state_dict['state']
        model.load_state_dict(state_dict)

    logger.info("Instruments: {}".format(config.training.instruments))

    device_ids = args.device_ids
    if torch.cuda.is_available():
        device = torch.device('cuda:0')
    else:
        device = 'cpu'
        logger.info('CUDA is not available. Run validation on CPU. It will be very slow...')

    if torch.cuda.is_available() and len(device_ids) > 1:
        valid_multi_gpu(model, args, config, device_ids, verbose=False)
    else:
        valid(model, args, config, device, verbose=True)


if __name__ == "__main__":
    check_validation(None)
