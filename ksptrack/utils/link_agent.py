import os
from os.path import join as pjoin
import numpy as np
import matplotlib.pyplot as plt
from imgaug import augmenters as iaa
from itertools import count
from ksptrack.utils import csv_utils as csv
import glob
from skimage.draw import circle
from skimage import io
from ksptrack.utils.lfda import myLFDA
from sklearn.decomposition import PCA
import warnings
import torch
from abc import ABC, abstractmethod

class LinkAgent(ABC):
    def __init__(self,
                 csv_path,
                 data_path,
                 thr_entrance=0.5):

        super().__init__()

        self.labels = np.load(pjoin(data_path, 'precomp_desc', 'sp_labels.npz'))['sp_labels']
        self.shape = self.labels[..., 0].shape
        self.trans_transform = None
        self.thr_clip = 0.05
        self.locs = csv.readCsv(csv_path, as_pandas=True)
        self.thr_entrance = thr_entrance


    def get_i_j(self, loc):
        i, j = csv.coord2Pixel(loc['x'], loc['y'], self.shape[1],
                               self.shape[0])
        return i, j

    def get_all_entrance_sps(self, sp_desc_df):

        sps = []

        for f in range(self.labels.shape[-1]):
            mask = self.make_entrance_mask(f) > self.thr_entrance
            labels_ = np.unique(self.labels[mask, f])
            descs_ = sp_desc_df[sp_desc_df['frame'] == f]
            descs_ = descs_.loc[descs_['label'].isin(labels_)]
            sps += [(f, row['label']) for _, row in descs_.iterrows()
                    if (mask[self.get_i_j(row)])]

        return sps

    @abstractmethod
    def make_entrance_mask(self, frame):
        pass

    def is_entrance(self, frame, label):
        """
        """

        mask = self.make_entrance_mask(frame)
        return np.mean(mask[self.labels[..., frame] == label]) > self.thr_entrance

    def get_closest_label(self, tl, tl_loc):
        loc_compare = self.locs.loc[self.locs['frame'] == tl.get_in_frame()]
        dists = [
            np.linalg.norm(
                np.array((tl_loc['x'], tl_loc['y'])) - np.array(r_compare))
            for r_compare in [(
                x, y) for x, y in zip(loc_compare['x'], loc_compare['y'])]
        ]
        loc_min = self.locs.loc[np.argmin(dists)]
        i_min, j_min = csv.coord2Pixel(loc_min['x'], loc_min['y'],
                                       self.shape[1], self.shape[0])
        return self.labels[i_min, j_min, tl.get_in_frame()]

    def make_trans_transform(self,
                             sp_desc,
                             pm,
                             threshs,
                             n_samps,
                             n_dims,
                             k,
                             embedding_type='weighted',
                             pca=False,
                             n_comps_pca=3):

        # descs_cat = utls.concat_arr(sp_desc['desc'])
        descs_cat = np.vstack(sp_desc['desc'].values)
        if (descs_cat.shape[1] == sp_desc.shape[0]):
            descs_cat = descs_cat.T

        if (not pca):

            self.trans_transform = myLFDA(n_components=n_dims,
                                          k=k,
                                          embedding_type=embedding_type)
            probas = pm['proba'].values
            if((probas < threshs[0]).sum() < n_samps):
                sorted_probas = np.sort(probas)
                threshs[0] = sorted_probas[n_samps]
                warnings.warn('Not enough negatives. Setting thr to {}'.format(threshs[0]))
            if((probas > threshs[1]).sum() < n_samps):
                sorted_probas = np.sort(probas)[::-1]
                threshs[1] = sorted_probas[n_samps]
                warnings.warn('Not enough positives. Setting thr to {}'.format(threshs[1]))
            self.trans_transform.fit(descs_cat, pm['proba'].values, threshs,
                                     n_samps)

        else:
            self.trans_transform = PCA(n_components=n_comps_pca, whiten=False)
            self.trans_transform.fit(descs_cat)