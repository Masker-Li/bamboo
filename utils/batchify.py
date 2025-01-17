# -----  BAMBOO: Bytedance AI Molecular Booster -----
# Copyright 2022-2024 Bytedance Ltd. and/or its affiliates 

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA


from typing import Dict

import torch
from torch_runstats.scatter import scatter

elemental_reference_energy = {
    8: -435.47248972,
    6: -154.05661131,
    1: -16.63427719,
    3: -114.4753,
    15: -114.4753,
    9: -659.92938527,
}

def batchify(data: dict, start: int, end: int, device: torch.device) -> Dict[str, torch.Tensor]:
    batch_data = dict()

    # molecule-level keys
    mol_keys = ['total_charge', 'energy', 'virial', 'dipole']
    for k in list(set(mol_keys) & set(data.keys())):
        batch_data[k] = data[k][start:end]
        # if k == 'virial':
        #     cell = data['cell'][start:end]
        #     volumn = cell[:, 0]*cell[:, 1]*cell[:, 2]
        #     batch_data[k] = - batch_data[k] * volumn.unsqueeze(1).unsqueeze(1)

    # atom-level keys
    atom_keys = ['pos', 'atom_types', 'forces', 'charge']
    for k in list(set(atom_keys) & set(data.keys())):
        batch_data[k] = data[k][data['cumsum_atom'][start]: data['cumsum_atom'][end]]
    batch_data['mol_ids'] = data['mol_ids'][data['cumsum_atom'][start]: data['cumsum_atom'][end]] - start

    # ========================== Modified start ==========================
    energy_ref = batch_data['atom_types'].clone().float()
    energy_ref.apply_(lambda x: elemental_reference_energy[x])
    energy_ref_mol = scatter(energy_ref, batch_data['mol_ids'], dim=0)
    batch_data['energy_ref'] = energy_ref_mol
    batch_data['energy'] = energy_ref_mol*23.0609 + batch_data['energy']
    # batch_data['energy'] = energy_ref_mol + batch_data['energy']/23.0609
    # batch_data['forces'] = batch_data['forces']/23.0609

    # nmol = int(torch.max(batch_data['mol_ids']).item()) + 1
    # force_mean = scatter(batch_data['forces'], batch_data['mol_ids'], dim=0, \
    #                      dim_size=nmol)/torch.bincount(batch_data['mol_ids']).unsqueeze(1)
    # force_mean_ = torch.gather(force_mean, 0, batch_data['mol_ids'].unsqueeze(1).repeat(1, 3))
    # virial_ = torch.einsum('ij,ik->ijk', batch_data['forces']-force_mean_, batch_data['pos'])
    # batch_data['virial'] = scatter(virial_, batch_data['mol_ids'], dim=0, dim_size=nmol)
    # batch_data['virial'] = (batch_data['virial'] + batch_data['virial'].transpose(1,2))/2
    # ========================== Modified end ==========================

    # edge-level keys
    batch_data['edge_index'] = (data['edge_index'][data['cumsum_edge'][start]: data['cumsum_edge'][end]] \
        - data['cumsum_atom'][start].unsqueeze(-1)).transpose(-2, -1).type(torch.long)
    if 'edge_cell_shift' in data:
        batch_data['edge_cell_shift'] = data['edge_cell_shift'][data['cumsum_edge'][start]: data['cumsum_edge'][end]]
    else:
        row, col = batch_data['edge_index'][0], batch_data['edge_index'][1]
        batch_data['edge_cell_shift'] = batch_data['pos'][row] - batch_data['pos'][col]
    batch_data['all_edge_index'] = (data['all_edge_index'][data['cumsum_all_edge'][start]: data['cumsum_all_edge'][end]] \
        - data['cumsum_atom'][start].unsqueeze(-1)).transpose(-2, -1).type(torch.long)
    if 'all_edge_cell_shift' in data:
        batch_data['all_edge_cell_shift'] = data['all_edge_cell_shift'][data['cumsum_all_edge'][start]: data['cumsum_all_edge'][end]]
    else:        
        row_all, col_all = batch_data['all_edge_index'][0], batch_data['all_edge_index'][1]
        batch_data['all_edge_cell_shift'] = batch_data['pos'][row_all] - batch_data['pos'][col_all]

    for k in batch_data.keys():
        batch_data[k] = batch_data[k].to(device)
        if torch.is_floating_point(batch_data[k]):
            batch_data[k] = batch_data[k].to(torch.get_default_dtype())
        elif batch_data[k].dtype == torch.int16:
            batch_data[k] = batch_data[k].to(torch.int64)
    return batch_data