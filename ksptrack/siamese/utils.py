import logging
import os
from os.path import join as pjoin
import yaml
import numpy as np
import torch
import shutil
from tqdm import tqdm
import networkx as nx
from itertools import combinations
from torch_geometric.data import Data
import torch_geometric.utils as gutls
from sklearn.neighbors import radius_neighbors_graph


def make_edges_ccl(model,
                   dataloader,
                   device,
                   probas=None,
                   drho=0.5,
                   radius=None,
                   return_subgraphs=False,
                   add_self_loops=False,
                   return_pos_labels=False,
                   return_signed=False):
    """Computes for each graph in dataloader its
    connected component edge list

    Args:
        model (pytorch model)
        dataloader
        """

    edges = []
    subgraphs = []

    for data in tqdm(dataloader):

        data = batch_to_device(data, device)

        with torch.no_grad():
            clst = model(data)['clusters'].argmax(dim=1).cpu().detach().numpy()

        if (radius is not None):
            graph = radius_neighbors_graph(data['centroids'], radius).tocoo()
        else:
            graph = nx.adjacency_matrix(data['graph'],
                                        nodelist=sorted(data['graph'].nodes()))
            graph = graph.tocoo()

        row = graph.row
        col = graph.col
        all_edges = np.vstack((row, col))

        # get edges according to cluster assignments
        edges_ = all_edges[:, clst[all_edges[0]] == clst[all_edges[1]]]

        if (probas is not None):
            # probas_ = probas[data['frame_idx'][0]]
            probas_ = torch.cat([probas[f] for f in data['frame_idx']])
            edges_ = edges_[:,
                            abs(probas_[edges_[0]] -
                                probas_[edges_[1]]) < drho]

        # create the induced subgraph of each component
        g = nx.Graph(edges_.T.tolist())
        S = [g.subgraph(c).copy() for c in nx.connected_components(g)]

        # all connected components form a fully connected group
        edges_ = [[(n0, n1, c) for n0, n1 in S_.edges]
                  for c, S_ in enumerate(S)]
        edges_ = [item for sublist in edges_ for item in sublist]
        edges_ = np.array(edges_)
        edges_ = torch.from_numpy(edges_).T.long()

        if (return_signed):
            edges_neg = all_edges[:, clst[all_edges[0]] != clst[all_edges[1]]]
            if (probas is not None):
                edges_neg = edges_neg[:,
                                      abs(probas_[edges_neg[0]] -
                                          probas_[edges_neg[1]]) <= drho]
            # edges_neg = np.array(edges_neg)
            edges_neg = torch.from_numpy(edges_neg).long()
            edges_neg = torch.cat(
                (edges_neg, -torch.ones(1, edges_neg.shape[1]).long()), dim=0)
            edges_ = torch.cat((edges_, edges_neg), dim=1)

        data = Data(edge_index=edges_)
        data.n_nodes = clst.size

        edges.append(data)

    if return_subgraphs:
        return edges, subgraphs

    return edges


def get_hard_constraint_edges(batch):

    max_node = 0
    nodes = []
    for i in range(len(batch['frame_idx'])):
        kps = batch['loc_keypoints'][i]
        if (not kps.empty):
            kps = kps.to_xy_array().astype(int)
            for kp in kps:
                label = int(batch['labels'][i, 0, kp[1], kp[0]].item())
                nodes.append(label + max_node)
        max_node += int(batch['labels'][i, ...].max().item()) + 1

    if (len(nodes) == 0):
        return None

    edges = np.array(list(combinations(nodes, 2)))
    return edges


def combine_nn_edges(edges_nn_list):

    combined_edges_nn = []
    max_node = 0
    for i in range(len(edges_nn_list)):
        combined_edges_nn.append(edges_nn_list[i] + max_node)
        max_node = edges_nn_list[i].max() + 1

    return torch.cat(combined_edges_nn, dim=0)


def make_single_graph_nn_edges(g, device, add_self_loops=True):

    if (add_self_loops):
        self_edges = [(n, n) for n in g.nodes()]
        g.add_edges_from(self_edges)

    all_nodes = np.array([n for n in g.nodes()])
    all_edges = np.array(list(combinations(all_nodes, 2)))

    centroids_x = np.array([g.nodes[n]['centroid'][0] for n in g])
    centroids_y = np.array([g.nodes[n]['centroid'][1] for n in g])

    dists = np.sqrt(
        (centroids_x[all_edges[:, 0]] - centroids_x[all_edges[:, 1]])**2 +
        (centroids_y[all_edges[:, 0]] - centroids_y[all_edges[:, 1]])**2)
    inds = np.argwhere(dists < nn_radius).ravel()

    edges_nn = torch.from_numpy(all_edges[inds, :]).to(device)

    return edges_nn


def make_couple_graphs(model,
                       device,
                       batch,
                       nn_radius,
                       do_inter_frame=True,
                       do_self_loop=True):
    """
    Builds edge array with nearest neighbors on same frame and next-frame
    Also assign clusters to each label according to DEC model
    
    nn_radius (float): Normalized radius to connect labels
    """

    g = batch['graph'][0]
    h = batch['graph'][1]

    # get cluster assignments from DEC model
    model.eval()
    batch = batch_to_device(batch, device)
    with torch.no_grad():
        clusters = model(batch)['clusters'].argmax(dim=-1)
    model.train()
    n_labels = [torch.unique(lab).numel() for lab in batch['labels']]
    clusters = torch.split(clusters, n_labels)

    # make NN graph
    mapping_1 = {n: n + g.number_of_nodes() for n in h}
    h_ = nx.relabel_nodes(h, mapping_1, copy=True)
    merged = nx.compose(g, h_)

    if (do_inter_frame):
        all_nodes = np.array([n for n in merged.nodes()])
        all_edges = list(combinations(all_nodes, 2))
        if (do_self_loop):
            all_edges += [(n, n) for n in all_nodes]
        all_edges = np.array(all_edges)
    else:
        all_nodes_0 = np.array([n for n in g.nodes()])
        all_nodes_1 = np.array([n for n in h_.nodes()])
        all_edges = list(combinations(all_nodes_0, 2)) + \
                             list(combinations(all_nodes_1, 2))
        if (do_self_loop):
            all_edges += [(n, n)
                          for n in np.concatenate((all_nodes_0, all_nodes_1))]

        all_edges = np.array(all_edges)

    centroids_x = np.array([merged.nodes[n]['centroid'][0] for n in merged])
    centroids_y = np.array([merged.nodes[n]['centroid'][1] for n in merged])

    dists = np.sqrt(
        (centroids_x[all_edges[:, 0]] - centroids_x[all_edges[:, 1]])**2 +
        (centroids_y[all_edges[:, 0]] - centroids_y[all_edges[:, 1]])**2)
    inds = np.argwhere(dists < nn_radius).ravel()

    edges_nn = torch.from_numpy(all_edges[inds, :]).to(device)

    return edges_nn, clusters[0].detach(), clusters[1].detach()


def make_all_couple_graphs(model,
                           device,
                           stack_loader,
                           nn_radius,
                           do_inter_frame=True):

    couple_graphs = nx.Graph()
    print('making NN-graphs')
    for sample in tqdm(stack_loader):
        edges_nn, clst0, clst1 = make_couple_graphs(model, device, sample,
                                                    nn_radius, do_inter_frame)
        couple_graphs.add_nodes_from([
            (n, dict(clst=c))
            for n, c in zip(sample['frame_idx'], [clst0, clst1])
        ])

        couple_graphs.add_edge(sample['frame_idx'][0],
                               sample['frame_idx'][1],
                               edges_nn=edges_nn,
                               clst=torch.cat((clst0, clst1)))

    return couple_graphs


def batch_to_device(batch, device):

    return {
        k: v.to(device) if (isinstance(v, torch.Tensor)) else v
        for k, v in batch.items()
    }


def to_onehot(arr_int, n_categories):
    b = np.zeros((arr_int.size, n_categories))
    b[np.arange(arr_int.size), arr_int] = 1
    return b


def setup_logging(log_path,
                  conf_path='logging.yaml',
                  default_level=logging.INFO,
                  env_key='LOG_CFG'):
    """Setup logging configuration

    """
    path = conf_path

    # Get absolute path to logging.yaml
    path = pjoin(os.path.dirname(__file__), path)
    value = os.getenv(env_key, None)
    if value:
        path = value
    if os.path.exists(path):
        with open(path, 'rt') as f:
            config = yaml.safe_load(f.read())
            config['handlers']['info_file_handler']['filename'] = pjoin(
                log_path, 'info.log')
            config['handlers']['error_file_handler']['filename'] = pjoin(
                log_path, 'error.log')
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)


def save_checkpoint(dict_,
                    is_best,
                    path,
                    fname_cp='checkpoint.pth.tar',
                    fname_bm='best_model.pth.tar'):

    cp_path = os.path.join(path, fname_cp)
    bm_path = os.path.join(path, fname_bm)

    if (not os.path.exists(path)):
        os.makedirs(path)

    state_dict = dict_['model'].state_dict()

    torch.save(state_dict, cp_path)

    if (is_best):
        shutil.copyfile(cp_path, bm_path)
