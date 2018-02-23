#!/usr/bin/python
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os, sys, argparse, glob
from scipy import signal
import numpy as np
from madmom.features import beats
from motion_format import motionread, calculate_rom, extract_beats, JOINTS
import utillib.BTET.beat_evaluation_toolbox as be
import pandas as pd

try:
  disp=os.environ['DISPLAY']
except Exception as e:
  import matplotlib as mpl
  mpl.use('Agg')
  pass
    
from matplotlib import pyplot as plt

def procesmadmomRNN(proc, filename):
  wav_fn = filename.replace('MOCAP/HTR', 'AUDIO/WAVE')
  wav_fn = wav_fn.replace('{}_'.format(args.exp), '')
  wav_fn = wav_fn.replace('test_', '')
  wav_fn = wav_fn.replace('.htr', '.wav')
  if not os.path.exists(wav_fn):
    mp3_fn = wav_fn.replace('WAVE', 'MP3')
    mp3_fn = mp3_fn.replace('wav', 'mp3')
    print('Wavefile not found in folder, converting from mp3 file.')
    os.system('sox {} -c 1 -r 16000 {}'.format(mp3_fn, wav_fn))
  act = beats.RNNBeatProcessor()(wav_fn)
  bpm = proc(act)
  bpm = np.unique(bpm)
  return bpm

def plot_vals(labels, means, stds, comp, title, idx):
  ind = np.arange(len(labels))
  width = 0.25
  fig, ax = plt.subplots()
  rects = [None] *means.shape[1]
  colors = ['r', 'b', 'g']
  for i in range(means.shape[1]):
    rects[i] = ax.bar(ind + i*width, means[:,i], width, color=colors[i], yerr=[stds[:,i,0],stds[:,i,1]]) #
  rects2 = ax.bar(ind + width, means[:,1], width, color='b', yerr=[stds[:,1,0],stds[:,1,1]]) #
  ax.set_title(title)
  ax.set_xticks(ind + width*i / 2)
  ax.set_xticklabels(labels) #rotation=40
  ax.legend(rects, comp)
  fig.savefig('{}/init_bpm_results_{}.png'.format(args.output, idx))
  return

def readfromfile(filename, folder):
  filename = filename.replace('MOCAP/HTR', folder) 
  filename = filename.replace('{}_'.format(args.exp), '')
  filename = filename.replace('test_', '')
  filename = filename.replace('.htr', '.txt')
  try:
    databeats = np.unique(np.loadtxt(filename))
  except Exception as e:
    databeats = None
    pass 
  return databeats

def main():
  with open(args.list) as f:
    filelist = f.readlines()
    filelist = [x.split('\n')[0] for x in filelist]

  proc = beats.BeatTrackingProcessor(fps=100)
  music_beat = []
  marsyas_beat = []
  mad_beat = []
  for fn in filelist:
    print(fn)
    databeats = readfromfile(fn,'Annotations/corrected')
    if databeats is None:
      raise ValueError('No music beat annotations found for exp {}, prepare first the beat annotations.'.format(args.exp))
    music_beat += [databeats]

    databeats = readfromfile(fn,'Annotations/Marsyas_ibt')
    if not databeats is None:
      marsyas_beat += [databeats]

    databeats = readfromfile(fn,'Annotations/madmom')
    if databeats is None:
      databeats = procesmadmomRNN(proc, fn)
      mdmfn = fn.replace('MOCAP/HTR', 'Annotations/madmom') 
      mdmfn = mdmfn.replace('{}_'.format(args.exp), '')
      mdmfn = mdmfn.replace('.htr', '.txt')
      np.savetxt(mdmfn,databeats, delimiter='\n', fmt='%.09f')
    mad_beat +=[databeats]

  evals_name = ['fMeasure']

  print('Aligning motion files with each music...')
  motion_beat = []
  align_idx = []
  #TODO: Needs to be parallelized (?)
  for i in range(len(music_beat)):
    _rot_quats = motionread(filelist[i], 'htr', 'euler', JOINTS)
    music_beat_frame = np.asarray(music_beat[i]*float(args.fps), dtype=np.int)
    precission = np.zeros((args.motionrange))
    align_beat = []
    for j in range(args.motionrange):
      rot_quats = _rot_quats[j:]
      motion_beat_frame = calculate_rom(rot_quats, args.alignframe)
      motion_beat_frame = extract_beats(music_beat_frame, motion_beat_frame, args.alignframe)
      align_beat += [motion_beat_frame.astype(np.float)/float(args.fps)]
      _, precission[j], _, _ = be.fMeasure(music_beat[i] , align_beat[j])
    align_idx += [np.where(precission==np.amax(precission))[0][0]] 
    motion_beat += [align_beat[align_idx[i]]]

  print('Evaluating MADMOM bpm')
  R_mad = be.evaluate_db(music_beat,mad_beat,measures='fMeasure', doCI=True)
  print('Evaluating Marsyas-ibt bpm')
  R_mar = be.evaluate_db(music_beat,marsyas_beat,measures='fMeasure', doCI=True)
  print('Evaluating MOTION bpm')
  R_mot = be.evaluate_db(music_beat,motion_beat,measures='fMeasure', doCI=True)

  init_results={ 'comparison' : ['Music-Madmom', 'Music-Marsyas', 'Music-Motion'],
    'fscore' : [R_mad['scores_mean']['fMeasure'], 
                R_mar['scores_mean']['fMeasure'],
                R_mot['scores_mean']['fMeasure']]}
  df = pd.DataFrame(init_results, columns = ['comparison', 'fscore'])
  df.to_csv('{}/init_results.csv'.format(args.output), encoding='utf-8')

  results =[R_mad, R_mot, R_mar]
  
  evals_mean = np.zeros((len(evals_name), len(results)))
  evals_std = np.zeros((len(evals_name), len(results),2))
  for i in range(len(evals_name)):
    for j in range(len(results)):
      evals_mean[i,j] = results[j]['scores_mean'][evals_name[i]]
      evals_std[i, j, 0] = np.abs(results[j]['scores_conf'][evals_name[i]][0] - evals_mean[i,j])
      evals_std[i, j, 1] = np.abs(results[j]['scores_conf'][evals_name[i]][1] - evals_mean[i,j])
  res_label=['Madmom', 'Dancer', 'Marsyas-ibt']
  plot_vals(evals_name, evals_mean, evals_std, res_label, 'Bootstrapping 95% confidence interval w.r.t. music beat', 1)
  
  align_txt = [ '{}\t{}'.format(filelist[i], align_idx[i]) for i in range(len(music_beat))]
  align_txt = '\n'.join(align_txt)
  with open('{}/{}_files_align.txt'.format(args.output, args.stage), 'w+') as f:
    f.write(align_txt)
  print('\nDone')

if __name__=='__main__':
  parser = argparse.ArgumentParser(description='BPM Evaluation')
  parser.add_argument('--list', '-l', type=str, help='File list')
  parser.add_argument('--exp', '-e', type=str, help='Experiment type')
  parser.add_argument('--output', '-o', type=str, help='Folder to save')
  parser.add_argument('--alignframe', '-a', type=int, help='Frames allowed to align', default=0)
  parser.add_argument('--motionrange', '-m', type=int, help='Range allowed between music and motion files', default=0)
  parser.add_argument('--fps', '-f', type=int, help='Motion file FPS', default=0)
  parser.add_argument('--stage', '-s', type=str, help='Train or Test')
  args = parser.parse_args()
  main()

