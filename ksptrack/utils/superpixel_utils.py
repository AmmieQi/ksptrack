import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import ndimage
from skimage import (io, segmentation)
import sys
import os
from . import csv_utils as csv
import tqdm


def getLabelCentroids(labels):
    """
    labels is a list of positive-integer matrix whose values refer to a label. Values must be contiguous.
    Returns: List of same length as labels, containing arrays with first element containing value of label, and second and third element containing the x and y coordinates of centroid.
    """

    nFrames = labels.shape[2]
    centroids = []

    centroid_list = []
    pbar = tqdm.tqdm(total=nFrames)

    for i in range(nFrames):
        idxLabels = np.unique(labels[:, :, i])
        for j in range(len(idxLabels)):
            thisMask = (labels[..., i] == idxLabels[j])
            pos = np.asarray(ndimage.measurements.center_of_mass(thisMask))
            pos_norm = csv.pix2Norm(pos[1], pos[0], labels.shape[1],
                                    labels.shape[0])
            centroid_list.append(
                [i, int(idxLabels[j]), pos_norm[0], pos_norm[1]])
        pbar.update(1)
    centroids = pd.DataFrame(
        centroid_list,
        columns=['frame', 'label', 'x', 'y'])

    return (centroids)


def drawLabelContourMask(img, labels, color=(255, 0, 0)):

    cont = segmentation.find_boundaries(labels, mode='thick')
    idx_cont = np.where(cont)
    img[idx_cont[0], idx_cont[1], :] = color

    return img
