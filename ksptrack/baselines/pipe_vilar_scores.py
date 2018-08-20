import glob
import os
import numpy as np
import datetime
from ruamel import yaml
import numpy as np
import munch
import matplotlib.pyplot as plt
import h5py
import pandas as pd
from sklearn.metrics import (f1_score, roc_curve, auc, precision_recall_curve)
from skimage.transform import resize
from labeling.exps import results_dirs as rd
from labeling.utils import my_utils as utls
from labeling.utils import learning_dataset
from labeling.cfgs import cfg

def adjust_path(root_dir, path_, prefix_remove=2):

    splits = utls.splitall(path_)
    return os.path.join(root_dir, *splits[prefix_remove:])

for key in rd.types:
#for key in ['Brain', 'Cochlea', 'Slitlamp']:
    for dir_ in rd.res_dirs_dict_vilar[key]:

        print('Scoring:')
        print(dir_)
        # Get h5 file
        path_ = os.path.join(rd.root_dir,
                             dir_)

        # Get config
        conf = cfg.load_and_convert(os.path.join(path_, 'cfg.yml'))

        conf.dataInRoot = rd.root_dir
        l_dataset = learning_dataset.LearningDataset(conf, pos_thr=0.5)
        gt = l_dataset.gt
        path_preds_im = os.path.join(path_,
                                     'vilar',
                                     'pred_im_*')
        pred_im_paths = sorted(glob.glob(path_preds_im))
        preds = np.asarray([np.load(f)['pred'] for f in pred_im_paths])
        preds = preds.transpose((1,2,0))

        gt = l_dataset.gt
        pr, rc, _ = precision_recall_curve(gt.ravel(),
                                           preds.ravel())
        all_f1s = 2 * (pr * rc) / (pr + rc)
        max_f1 = np.nanmax(all_f1s)
        max_pr = pr[np.argmax(all_f1s)]
        max_rc = rc[np.argmax(all_f1s)]
        f1_thr_ind = np.argmax(2 * (pr * rc) / (pr + rc))
        file_out = os.path.join(conf.dataOutDir, 'scores.csv')

        C = pd.Index(["F1", "F1_thr_ind", "PR", "RC"], name="columns")
        I = pd.Index(['WTP'], name="Methods")
        data = np.asarray([max_f1, f1_thr_ind, max_pr, max_rc]).reshape(1, 4)
        df = pd.DataFrame(data=data, index=I, columns=C)
        print('Saving F1 score')
        df.to_csv(path_or_buf=file_out)

        print('Saving (resized?) predictions')
        np.savez(os.path.join(conf.dataOutDir, 'preds.npz'),
                 **{'preds': preds})

        #l_dataset.gt
