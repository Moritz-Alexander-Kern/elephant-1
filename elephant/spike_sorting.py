import warnings
import atexit
import tempfile
import numpy as np
import copy
import quantities as pq
import os.path
from os import linesep as sep

# Recommended spike sort version is 'dev' branch.
# The SpikeSort/src folder needs to be added to the PYTHONPATH,
# but no installation of SpikeSort is required.
try:
    import spike_sort
except ImportError:
    spike_sort = None
    warnings.warn('Could not import spike_sort.'
                  ' No SpikeSort (www.spikesort.org) functionality available for spike extraction and clustering.')

# It is not necessary to install Phy. Downloading the current
# version and adding it the PYTHONPATH is sufficient/recommended.
# However, Klustakwik2 (https://github.com/kwikteam/klustakwik2)
# needs to be installed in order to perform spike clustering
try:
    import phy.io
    import phy.session
except ImportError:
    phy = None
    warnings.warn('Could not import Phy.'
                  ' No Phy (www.phy.readthedocs.org) functionality available for spike extraction and clustering.')
import neo
import elephant

parameter_templates = {
    'spikesort' : {
        'extraction_dict':{'sp_win_extract': [-0.5*pq.ms, 1.5*pq.ms],
                                    'sp_win_align': [-1*pq.ms, 1*pq.ms],
                                    'filter': [500*pq.Hz, None],
                                    'filter_order': 4,
                                    'threshold': 'auto',
                                    #'remove_doubles': 0.25*pq.ms,
                                    'edge': 'falling'},

        'sorting_dict':{   'method':'k-means-plus',
                                    'num_units': 3,
                                    'ncomps': 2}
        },

    'phy' : {
        'experiment_name' : 'dummy_experiment',
        'prb_file' :      'probe',
        'spikedetekt' : {   'filter_low':500.,  # Low pass frequency (Hz)
                            'filter_high_factor':0.95 * .5,
                            'filter_butter_order':3,  # Order of Butterworth filter.

                            'filter_lfp_low':0,  # LFP filter low-pass frequency
                            'filter_lfp_high':500,  # LFP filter high-pass frequency

                            'waveform_filter': 1,
                            'waveform_scale_factor': 1,
                            'waveform_dc_offset': 0,

                            'chunk_size_seconds':10,
                            'chunk_overlap_seconds':0.15,

                            'n_excerpts':50,
                            'excerpt_size_seconds':1,
                            'threshold_strong_std_factor':4.5,
                            'threshold_weak_std_factor':2.,
                            'use_single_threshold': 1,
                            'detect_spikes':'negative',

                            'connected_component_join_size':1,

                            'extract_s_before':16,
                            'extract_s_after':16,

                            'n_features_per_channel':3,  # Number of features per channel.
                            'pca_n_waveforms_max':10000,
                            'weight_power': 2},


        'klustakwik2' : {
                            'always_split_bimodal': False,
                             'break_fraction': 0.0,
                             'consider_cluster_deletion': True,
                             'dist_thresh': 9.2103403719761836,
                             'fast_split': False,
                             'full_step_every': 1,
                             'max_iterations': 1000,
                             'max_possible_clusters': 1000,
                             'max_quick_step_candidates': 100000000,
                             'max_quick_step_candidates_fraction': 0.4,
                             'max_split_iterations': None,
                             'mua_point': 2,
                             'noise_point': 1,
                             'num_changed_threshold': 0.05,
                             'num_cpus': 1,
                             'num_starting_clusters': 500,
                             'penalty_k': 0.0,
                             'penalty_k_log_n': 1.0,
                             'points_for_cluster_mask': 100,
                             'prior_point': 1,
                             'split_every': 40,
                             'split_first': 20,
                             'subset_break_fraction': 0.01,
                             'use_mua_cluster': True,
                             'use_noise_cluster': True,
                             'log' : True,
        }
    },
    'manual' : {
        'extraction_dict' : {
                         'filter_high':400*pq.Hz,
                         'filter_low':None,
                         'threshold':-4.5,
                         'n_pre':-10, 'n_post':10,
                         'alignment':'min'
        }
    }
}


def get_updated_parameters(software,new_parameters):
    # get template parameters
    if software in parameter_templates:
        template = copy.deepcopy(parameter_templates[software])
    else: raise ValueError('No spike sorting software with name "%s" known. '
                           'Available softwares include %s'%(software,parameter_templates.keys()))


    for key, value in new_parameters.iteritems():
        # scan if this key is available in template and should be overwritten
        overwritten = False
        for template_section_name, template_section in template.iteritems():
            if hasattr(template_section,'iteritems'):
                for template_key, template_value in template_section.iteritems():
                    if key == template_key:
                        template[template_section_name][template_key] = value
                        overwritten = True

        if software == 'spikesort':
            # translation of similar keywords (for better compatibility between sorting softwares available)
            if key == 'filter_low':
                template['extraction_dict']['filter'][1] = value * pq.Hz
                overwritten = True
            elif key == 'filter_high':
                template['extraction_dict']['filter'][0] = value * pq.Hz
                overwritten = True
            elif key == 'extract_s_before':
                template['extraction_dict']['sp_win_extract'][0] = -1*value
                overwritten = True
            elif key == 'extraction_s_after':
                template['extraction_dict']['sp_win_extract'][1] = value
                overwritten = True

        elif software == 'phy':
            # translation of similar keywords (for better compatibility between sorting softwares available)
            if key == 'filter':
                if value[0] != None:
                    template['spikedetekt']['filter_high'] = value[0].rescale('Hz').magnitude
                else:
                    template['spikedetekt']['filter_high'] = 0
                if value[1] != None:
                    template['spikedetekt']['filter_low'] = value[1].rescale('Hz').magnitude
                else:
                    template['spikedetekt']['filter_low'] = 0
                overwritten = True
            elif key == 'sp_win_extract':
                template['spikedetekt']['extraction_s_before'] = -1*value[0]
                template['spikedetekt']['extraction_s_after'] = value[0]
                overwritten = True
            elif key == 'filter_order':
                template['spikedetekt']['filter_butter_order'] = value
                overwritten = True
            elif key == 'filter_order':
                template['spikedetekt']['filter_butter_order'] = value
                overwritten = True
            elif key == 'egde':
                if value == 'falling':
                    value = 'negative'
                elif value == 'rising':
                    value = 'positive'
                template['spikedetekt']['detect_spikes'] = value
                overwritten = True
            elif key == 'threshold':
                warnings.warn('Assuming threshold of %s as strong_threshold_std_factor'
                              ' for spike extraction with phy.'%value)
                template['spikedetekt']['threshold_strong_std_factor'] = value
                overwritten = True

        elif software == 'manual':
            pass

        else:
            raise ValueError('Unknown spike sorting software "%s"'%software)

        if overwritten == False:
            warnings.warn('Could not assign spike extraction parameter '
                          'value "%s" to any parameter named "%s" or similar'%(value,key))

    return template



def requires(module, msg):
    # This function is copied from Phy Cluster module
    def _decorator(func):
        def _wrapper(*args, **kwargs):
            if module is None:
                raise NotImplementedError(msg)
            else:
                return func(*args, **kwargs)
        _wrapper.__doc__ = func.__doc__
        return _wrapper
    return _decorator



@requires(spike_sort,'SpikeSort must be available to extract spikes with this method.')
def generate_spiketrains_from_spikesort(block, waveforms=True, sort=True, extraction_dict={}, sorting_dict={}):
    """
    Extracting spike times and waveforms from analogsignals in neo block object. This method uses functions
    of the spike_sort module and has not yet been tested extensively. Use at own risk.
    :param block: (neo block object) neo block which contains analogsignalarrays for spike extraction
    :param extraction_dict: (dict) additional parameters used for spike extraction
                    Automatically used parameters are:
                        {'sp_win_extract':[-0.5*pq.ms,1.5*pq.ms],'sp_win_align':[-1*pq.ms,1*pq.ms],
                        'remove_doubles':0.25*pq.ms, 'filter':[500*pq.Hz,None],'filter_order':4,
                        'threshold':'auto', 'edge':'falling'}
    :param sorting_dict: (dict) additional parameters used for spike sorting
                    Automatically used parameters are:
                        {'num_units':3,'ncomps':2}
    :return: None
    """

    def ss_wrap(anasig, contact=1):
        return {'n_contacts': contact, 'data': np.asarray(anasig).reshape((1, -1)),
                'FS': anasig.sampling_rate.rescale('Hz').magnitude}

    def fetPCA(sp_waves, ncomps=2):
            """
            Calculate principal components (PCs).

            Parameters
            ----------
            spikes : dict
            ncomps : int, optional
                number of components to retain

            Returns
            -------
            features : dict
            """

            data = sp_waves['data']
            n_channels = data.shape[2]
            pcas = np.zeros((n_channels*ncomps, data.shape[1]))

            for ch in range(n_channels):
                _, _, pcas[ch::data.shape[2], ] = spike_sort.features.PCA(data[:, :, ch], ncomps)

            names = ["ch.%d:PC%d" % (j+1, i+1) for i in range(ncomps) for j in range(n_channels)]

            outp = {'data': pcas.T}
            if 'is_valid' in sp_waves:
                outp['is_valid'] = sp_waves['is_valid']
            outp['time'] = sp_waves['time']
            outp['FS'] = sp_waves['FS']
            outp['names'] = names

            return outp

    for seg in block.segments:
        for anasig in seg.analogsignalarrays:
            # Frequency filtering for spike detection in two steps for better filter stability
            filtered_ana = copy.deepcopy(anasig)
            if extraction_dict['filter'][0] is not None:
                filtered_ana = elephant.signal_processing.butter(filtered_ana, highpass_freq=extraction_dict['filter'][0],
                                                                 lowpass_freq=None, order=extraction_dict['filter_order'],
                                                                 filter_function='filtfilt', fs=1.0, axis=-1)
            if extraction_dict['filter'][1] is not None:
                filtered_ana = elephant.signal_processing.butter(filtered_ana, highpass_freq=None,
                                                                 lowpass_freq=extraction_dict['filter'][1],
                                                                 order=extraction_dict['filter_order'],
                                                                 filter_function='filtfilt', fs=1.0, axis=-1)
            if any(np.isnan(filtered_ana)):
                raise ValueError('Parameters for filtering (%s, %s) yield non valid analogsignal'
                                 % (extraction_dict['filter'], extraction_dict['filter_order']))

            spt = spike_sort.extract.detect_spikes(ss_wrap(filtered_ana), contact=0, thresh=extraction_dict['threshold'],
                                                   edge=extraction_dict['edge'])
            spt = spike_sort.extract.align_spikes(ss_wrap(anasig), spt,
                                                  [i.rescale('ms').magnitude for i in extraction_dict['sp_win_align']],
                                                  type="min", contact=0, resample=1, remove=False)
            if 'remove_doubles' in extraction_dict:
                spt = spike_sort.core.extract.remove_doubles(spt, extraction_dict['remove_doubles'])

            if waveforms or sort:
                sp_waves = spike_sort.extract.extract_spikes(ss_wrap(anasig), spt,
                                                             [i.rescale('ms').magnitude
                                                             for i in extraction_dict['sp_win_extract']],
                                                             contacts=0)

                #  align waveform in y-axis
                for waveform in range(sp_waves['data'].shape[1]):
                    sp_waves['data'][:, waveform, 0] -= np.mean(sp_waves['data'][:, waveform, 0])

                if sort:
                    if len(spt['data']) > sorting_dict['ncomps']:
                        features = fetPCA(sp_waves, ncomps=sorting_dict['ncomps'])
                        clust_idx = spike_sort.cluster.cluster(sorting_dict['method'], features, sorting_dict['num_units'])
                        # clustered spike times
                        spt_clust = spike_sort.cluster.split_cells(spt, clust_idx)
                    else:
                        warnings.warn('Spike sorting on electrode %i not possible due to low number of spikes.'
                                      ' Perhaps the threshold for spike extraction is too conservative?'
                                      % anasig.annotations['electrode_id'])
                        spt_clust = {0: spt}
                        clust_idx = np.array([0])

                    if waveforms and len(spt['data']) > sorting_dict['ncomps']:
                        sp_waves = dict([(cl, {'data': sp_waves['data'][:, clust_idx == cl, :]})
                                         for cl in np.unique(clust_idx)])
                    else:
                        sp_waves = {0: sp_waves}


            # Create SpikeTrain objects for each unit
            # Unit id 0 == Mua; unit_id >0 => Sua
            spiketrains = {i+1: j for i, j in spt_clust.iteritems()} if sort else {0: spt}
            sp_waves = {i+1: j for i, j in sp_waves.iteritems()} if waveforms and sort else {0: sp_waves}
            for unit_i in spiketrains:
                sorted = sort
                sorting_params = sorting_dict if sort else None
                spiketimes = spiketrains[unit_i]['data'] * pq.ms + anasig.t_start

                st = neo.SpikeTrain(times=spiketimes,
                                    t_start=anasig.t_start,
                                    t_stop=anasig.t_stop,
                                    sampling_rate=anasig.sampling_rate,
                                    name="Channel %i, Unit %i" % (anasig.annotations['channel_index'], unit_i),
                                    file_origin=anasig.file_origin,
                                    unit_id=unit_i,
                                    channel_id=anasig.annotations['channel_index'],
                                    electrode_id=anasig.annotations['electrode_id'],
                                    sorted=sorted,
                                    sorting_parameters=sorting_params,
                                    extraction_params=extraction_dict)

                if waveforms and not any([d==0 for d in sp_waves[unit_i]['data'].shape]):
                    if sp_waves[unit_i]['data'].shape[2] != 1:
                        raise ValueError('Unexpected shape of waveform array.')
                    # waveform dimensions [waveform_id,???,time]
                    st.waveforms = np.transpose(sp_waves[unit_i]['data'][:,:,0]) * anasig.units
                    st.waveforms = st.waveforms.reshape((st.waveforms.shape[0],1,st.waveforms.shape[1]))
                    st.left_sweep = extraction_dict['sp_win_align'][0]
                    # st.spike_duration = extraction_dict['sp_win_align'][1] - extraction_dict['sp_win_align'][0]
                    # st.right_sweep = extraction_dict['sp_win_align'][1]
                else:
                    st.waveforms = None

                # connecting unit, spiketrain and segment
                rcgs = anasig.recordingchannel.recordingchannelgroups
                u_annotations = {'sorted': sorted,
                                 'parameters':{ 'sorting_params': sorting_params,
                                                'extraction_params': extraction_dict}}

                new_unit = None
                for rcg in rcgs:
                    # checking if a similar unit already exists (eg. from sorting a different segment)
                    rcg_units = [u for u in rcg.units if u.name == st.name and u.annotations == u_annotations]
                    if len(rcg_units) == 1:
                        unit = rcg_units[0]
                    elif len(rcg_units) == 0:
                        # Generating new unit if necessary
                        if new_unit is None:
                            new_unit = neo.core.Unit(name=st.name, **u_annotations)
                        unit = new_unit
                    else:
                        raise ValueError('%i units of name %s and annotations %s exists.'
                                         ' This is ambiguous.' % (len(rcg_units), st.name, u_annotations))
                    rcg.units.append(unit)
                    unit.spiketrains.append(st)
                seg.spiketrains.append(st)


#######################################################################################################################

@requires(phy,'Phy must be available to extract spikes with this method.')
def generate_spiketrains_from_phy(block, waveforms=True, sort=True, parameter_dict={}):

    original_parameters = copy.deepcopy(parameter_dict)

    session_name = block.name
    random_id = np.random.randint(0,10**10)
    tempdir = tempfile.gettempdir()
    prm_file_name = os.path.join(tempdir,'temp_phy_params_%s_%i.prm'%(session_name,random_id))
    prb_file_name = os.path.join(tempdir,'temp_phy_probe_%s_%i.prb'%(session_name,random_id))
    dummy_data_file_name = os.path.join(tempdir,'temp_phy_dummy_data_%s_%i.dat'%(session_name,random_id))
    kwik_file_name = os.path.join(tempdir,'temp_phy_session_%s_%i.kwik'%(session_name,random_id))

    def remove_temp_files(temp_files):
        for temp_file in temp_files:
            if os.path.isfile(temp_file):
                os.remove(temp_file)
            elif os.path.isdir(temp_file):
                os.rmdir(temp_file)


    # removing temporary files after program finished
    if 'keep_temp_files' in parameter_dict:
        if not parameter_dict['keep_temp_files']:
            atexit.register(remove_temp_files,[prm_file_name,
                                               prb_file_name,
                                               dummy_data_file_name,
                                               kwik_file_name,
                                               # also remove files generated during spikesorting
                                               os.path.join(tempdir,kwik_file_name.replace('.kwik','.phy')),
                                               os.path.join(tempdir,kwik_file_name.replace('.kwik','.kwx')),
                                               os.path.join(tempdir,kwik_file_name.replace('.kwik','.log')),
                                               os.path.join(tempdir,kwik_file_name + '.bak')])
        parameter_dict.pop('keep_temp_files')


    def add_traces_to_params(block):
        # Extracting sampling rate
        sampling_rate = None
        n_channels = None
        for seg in block.segments:
            for anasig in seg.analogsignalarrays:
                if sampling_rate == None:
                    sampling_rate = anasig.sampling_rate
                elif sampling_rate != anasig.sampling_rate:
                    raise ValueError('Analogsignalarrays have different sampling rates. '
                                     'Phy can not extract spikes from signals with varying sampling rates.')
            if n_channels == None:
                n_channels = len(seg.analogsignalarrays)
            elif n_channels != len(seg.analogsignalarrays):
                raise ValueError('Segments contain different numbers of Analogsignalarrays. '
                                 'Phy can not deal with different numbers of channels in one session.')


        parameter_dict['traces'] ={'raw_data_files':dummy_data_file_name,
                                   'voltage_gain':1.0,
                                   'sample_rate':sampling_rate.rescale('Hz').magnitude,
                                   'n_channels':n_channels,
                                   'dtype':'int16'}


    def generate_prm_file(phy_params):
        with open(prm_file_name, 'w') as f:
            for key0 in phy_params.iterkeys():
                if isinstance(phy_params[key0],dict):
                    f.write('%s = dict(%s'%(key0,sep))
                    for key, value in phy_params[key0].iteritems():
                        if isinstance(value,str):
                            value = "'%s'"%value
                        f.write('\t%s = %s,%s'%(key,value,sep))
                    f.write(')%s'%sep)
                else:
                    value = phy_params[key0]
                    if isinstance(value,str):
                        value = "'%s'"%value
                    f.write('%s = %s%s'%(key0,value,sep))

    def generate_prb_file(phy_params,probe_type='linear'):
        if probe_type=='linear':
            n_channels = phy_params['traces']['n_channels']
            if n_channels == 1:
                warnings.warn('Individual spikes on multiple contacts can not be detected'
                              ' if spike sorting is performed on individual contacts (n_channels=1).')
            with open(prb_file_name, 'w') as f:
                f.write('channel_groups = {%s'%sep)
                f.write('\t0: {%s'%sep)
                f.write("\t\t'channels': %s,%s"%(range(n_channels),sep))
                f.write("\t\t'graph': %s,%s"%([[i,i+1] for i in range(n_channels-1)],sep))
                f.write("\t\t'geometry': %s%s"%(dict([[i,[0.0,float(i)/10]] for i in range(n_channels)]),sep))
                f.write('\t}%s'%sep)
                f.write('}')
        else:
            raise NotImplementedError('This functionality is only implemented for linear probes.')

    def generate_dummy_data_file():
        with open(dummy_data_file_name, 'w') as f:
            f.write('dummy data')


    add_traces_to_params(block)
    parameter_dict['prb_file'] = prb_file_name.split(os.path.sep)[-1]
    generate_prm_file(parameter_dict)
    generate_prb_file(parameter_dict,probe_type='linear')
    generate_dummy_data_file()


    if os.path.isfile(kwik_file_name):
        warnings.warn('Deleting old kwik file %s to generate new spike sorting'%kwik_file_name)
        os.remove(kwik_file_name)

    # creating new kwik file for phy session
    probe = phy.io.kwik.creator.load_probe(prb_file_name)
    phy.io.create_kwik(prm_file_name,kwik_file_name,overwrite=False,probe=probe)

    # generating phy session
    phy_session = phy.session.Session(kwik_file_name)

    def merge_annotations(A, B):
        """
        From neo.core.baseneo, modified
        Merge two sets of annotations.

        Merging follows these rules:
        All keys that are in A or B, but not both, are kept.
        For keys that are present in both:
            For arrays or lists: concatenate
            For dicts: merge recursively
            For strings: concatenate with ';'
            Otherwise: fail if the annotations are not equal
        """
        merged = {}
        for name in A:
            if name in B:
                try:
                    merged[name] = merge_annotation(A[name], B[name])
                except BaseException as exc:
                    exc.args += ('key %s' % name,)
                    raise
            else:
                merged[name] = A[name]
        for name in B:
            if name not in merged:
                merged[name] = B[name]
        return merged


    def merge_annotation(a, b):
            """
            From neo.core.baseneo, modified
            First attempt at a policy for merging annotations (intended for use with
            parallel computations using MPI). This policy needs to be discussed
            further, or we could allow the user to specify a policy.

            Current policy:
                For arrays or lists: concatenate
                For dicts: merge recursively
                For strings: concatenate with ';'
                Otherwise: fail if the annotations are not equal
            """

            if isinstance(a, list):  # concatenate b to a
                if isinstance(b, list):
                    return a + b
                else:
                    return a.append(b)

            if type(a) != type(None) and type(b) != type(None):
                assert type(a) == type(b), 'type(%s) %s != type(%s) %s' % (a, type(a),
                                                                       b, type(b))
            if isinstance(a, dict):
                return merge_annotations(a, b)
            elif isinstance(a, np.ndarray):  # concatenate b to a
                return np.append(a, b)
            elif isinstance(a, basestring):
                if a == b:
                    return a
                else:
                    return a + ";" + b
            else:
                return [a,b]

    def hstack_signals(sig1,sig2):
        # This function is partially copied form neo analogsignal merge()
        sig1 = copy.deepcopy(sig1)
        sig2 = copy.deepcopy(sig2)
        assert sig1.sampling_rate == sig2.sampling_rate
        assert sig1.t_start == sig2.t_start
        assert len(sig1) == len(sig2)
        sig2.units = sig1.units
        # stack = np.hstack(np.array,(sig1,sig2.reshape(-1,1))) #np.hstack(map(np.array, (sig1, sig2)))
        kwargs = {}
        for name in ("name", "description", "file_origin","channel_index",'sampling_rate'):
            attr_sig1 = getattr(sig1, name)
            attr_sig2 = getattr(sig2, name)
            # if (not(hasattr(attr_sig1,'__iter__') or hasattr(attr_sig2,'__iter__')) \
            #     or ((type(attr_sig1)==pq.Quantity) and type(attr_sig2)==pq.Quantity)) \
            #         and attr_sig1 == attr_sig2:
            try:
                if attr_sig1 == attr_sig2:
                    kwargs[name] = attr_sig1
                else:
                    raise ValueError()
            except:
            # else:
                if type(attr_sig1) != list:
                    attr_sig1 = [attr_sig1]
                if type(attr_sig2) != list:
                    attr_sig2 = [attr_sig2]
                attr_sig1 = attr_sig1 + attr_sig2
                setattr(sig1,name,attr_sig1)
                setattr(sig2,name,attr_sig1)

        if 'channel_index' in sig1.annotations:
            sig1.annotations.pop('channel_index')
        if 'sampling_rate' in sig1.annotations:
            sig1.annotations.pop('sampling_rate')
        if 't_start' in sig1.annotations:
            sig1.annotations.pop('t_start')

        merged_annotations = merge_annotation(sig1.annotations,
                                               sig2.annotations)

        sig2 = sig2.reshape((-1,1))

        stacked = np.hstack((sig1,sig2))
        stacked.__dict__ = sig1.__dict__.copy()
        stacked.annotations = merged_annotations

        return stacked

    def kwik_spikes_to_neo_block(seg,traces,waveforms, sort):
        #read results from kwik file(s) or phy_session

        kwikfile = phy.io.h5.File(kwik_file_name)
        kwikfile.open()
        time_samples = kwikfile.read('/channel_groups/0/spikes/time_samples')
        time_fractional = kwikfile.read('channel_groups/0/spikes/time_fractional')
        cluster_ids = np.asarray(kwikfile.read('/channel_groups/0/spikes/clusters/main'))
        spike_channel_masks = np.asarray([phy_session.model.masks[i] for i in range(len(time_samples))])

        phy_session.store.is_consistent()

        if waveforms:
            try:
                kwxfile = phy.io.h5.File(kwik_file_name.replace('.kwik','.kwx'))
                kwxfile.open()
                if kwxfile.exists('/channel_groups/0/waveforms_raw'):
                    waveforms_raw = kwxfile.read('/channel_groups/0/waveforms_raw')
                else:
                    waveforms_raw = phy_session.model.waveforms[range(phy_session.n_spikes)]

                # if kwxfile.exists('/channel_groups/0/waveforms_filtered'):
                #     waveforms_filtered = kwxfile.read('/channel_groups/0/waveforms_filtered')
                # else:
                #     waveforms_filtered = phy_session.store.waveforms(0,'filtered')
                if kwxfile.exists('/channel_groups/0/features_masks'):
                    features_masks = kwxfile.read('/channel_groups/0/features_masks')
                else:
                    features = phy_session.store.features(0)
                    features_masks = phy_session.model.features_masks[range(phy_session.n_spikes)]
            except KeyError:
                warnings.warn('Could not extract wavefroms from kwik file or phy_session due to inconsistencies.')
                waveforms = False

        spiketimes = (np.asarray(time_samples) / traces.sampling_rate) + t_start

        for i,unit_id in enumerate(np.unique(cluster_ids)):
            unit_mask = cluster_ids == unit_id

            for channel_id in range(phy_session.model.n_channels):
                print 'unit %i, channel %i'%(unit_id,channel_id)
                channel_id = int(channel_id)
                unit_channel_mask = np.where(np.logical_and(spike_channel_masks[:,channel_id] > 0, unit_mask) == True)
                unit_spikes = spiketimes[unit_channel_mask]

                if len(unit_spikes) < 1:
                    continue

                original_anasig = seg.analogsignalarrays[channel_id]

                # generating spiketrains
                st = neo.SpikeTrain(times=unit_spikes,
                                    t_start=traces.t_start,
                                    t_stop=traces.t_stop,
                                    sampling_rate=traces.sampling_rate,
                                    name="Channel %i, Unit %i" % (original_anasig.channel_index, unit_id),
                                    file_origin=traces.file_origin,
                                    unit_id=unit_id,
                                    channel_id=anasig.annotations['channel_index'],
                                    electrode_id=anasig.annotations['electrode_id'],
                                    sorted=sort,
                                    sorting_parameters=parameter_dict['klustakwik2'],
                                    extraction_params=parameter_dict['spikedetekt'],
                                    prb_file=parameter_dict['prb_file'],
                                    # channel_affiliations=spike_channel_masks[unit_channel_mask,channel_id]
                                    )

                if waveforms:
                    # waveform dimensions [waveform_id,??,time]
                    st.waveforms = waveforms_raw[unit_channel_mask][:,:,channel_id] * original_anasig.units
                    st.waveforms = st.waveforms.reshape((st.waveforms.shape[0],1,st.waveforms.shape[1]))
                    st.left_sweep = -1 * parameter_dict['spikedetekt']['extract_s_before'] / anasig.sampling_rate
                    # st.spike_duration = (parameter_dict['spikedetekt']['extract_s_after']) / anasig.sampling_rate  -st.left_sweep
                    # st.right_sweep = parameter_dict['spikedetekt']['extract_s_after'] / anasig.sampling_rate
                else:
                    st.waveforms = None

                # connecting unit, spiketrain and segment
                rcgs = anasig.recordingchannel.recordingchannelgroups
                u_annotations = {'sorted': sort,
                                 'parameters': original_parameters}

                new_unit = None
                for rcg in rcgs:
                    # checking if a similar unit already exists (eg. from sorting a different segment)
                    rcg_units = [u for u in rcg.units if u.name == st.name and u.annotations == u_annotations]
                    if len(rcg_units) == 1:
                        unit = rcg_units[0]
                    elif len(rcg_units) == 0:
                        # Generating new unit if necessary
                        if new_unit is None:
                            new_unit = neo.core.Unit(name=st.name, **u_annotations)
                        unit = new_unit
                    else:
                        raise ValueError('%i units of name %s and annotations %s exists.'
                                         ' This is ambiguous.' % (len(rcg_units), st.name, u_annotations))
                    rcg.units.append(unit)
                    unit.spiketrains.append(st)
                seg.spiketrains.append(st)





    # get maximal time period, where all analogsignals are present and collect signals in analogsignalarray
    for seg in block.segments:
        traces = None
        for anasig in seg.analogsignalarrays:
            if type(traces) == type(None):
                traces = anasig.reshape((-1,1))

            else:
                # adjusting length of signals
                if anasig.t_start<traces.t_start:
                    anasig.timeslice(traces.t_start,None)
                elif anasig.t_start>traces.t_start:
                    traces.time_slice(anasig.t_start,None)

                if anasig.t_stop>traces.t_stop:
                    anasig.timeslice(None,traces.t_stop)
                elif anasig.t_stop<traces.t_stop:
                    traces.time_slice(None,traces.t_stop)

                # merging signals into one analogsignalarray
                traces = hstack_signals(traces,anasig)

        t_start, t_stop = traces.t_start, traces.t_stop

        #detecting spikes using blank kwik file and lfp traces from neo block
        print 'Starting spike detection and extraction on %i (%i) anasigs.'%(len(seg.analogsignalarrays), traces.shape[1])
        phy_session.detect(np.asarray(traces))
        phy_session.save()

        if sort:
            print 'Starting spike clustering.'
            phy_session.cluster()
            phy_session.save()


        kwik_spikes_to_neo_block(seg,traces,waveforms,sort)


def generate_spiketrains_unsorted(block, waveforms=False, extraction_dict=None):

    filter_high = extraction_dict['filter_high']
    filter_low = extraction_dict['filter_low']
    threshold = extraction_dict['threshold']
    if waveforms:
        n_pre, n_post = [extraction_dict[key] for key in ['n_pre','n_post']]
        alignment = extraction_dict['alignment']

    def get_threshold_crossing_ids(sig,threshold):
        # normalize threshold to be positive
        if threshold < 0:
            threshold = -threshold
            sig = sig*(-1)
        # calculate ids at which signal crosses threshold value
        crossings = (threshold - sig).magnitude
        crossings *= (crossings>0)
        mask_bool = crossings.astype(bool).astype(int)
        crossing_ids = np.where(np.diff(mask_bool)==-1)[0]
        return crossing_ids

    def check_threshold(threshold,signal):
        if isinstance(threshold,pq.quantity.Quantity):
            thres = threshold
        elif isinstance(threshold,(int,float)):
            warnings.warn('Assuming threshold is given in standard deviations '
                          'of the signal amplitude')
            thres = threshold*np.std(sig)
        else:
            raise ValueError('Unknown threshold unit "%s"'%threshold)
        return thres

    for seg in block.segments:
        for anasig_id, anasig in enumerate(seg.analogsignalarrays):
            sig = elephant.signal_processing.butter(anasig, filter_high,
                                                    filter_low)

            thres = check_threshold(threshold,sig)

            ids = get_threshold_crossing_ids(sig, thres)

            # remove border ids
            ids = ids[np.logical_and(ids > -n_pre, ids < (len(sig)-n_post))]

            st = neo.SpikeTrain(anasig.times[ids], unit_id=None, sorted=False,
                name="Channel %i, Unit %i" % (anasig.channel_index, -1),
                t_start=anasig.t_start,t_stop=anasig.t_stop,
                sampling_rate=anasig.sampling_rate,
                electrode_id=anasig.annotations['electrode_id'],
                channel_index=anasig.annotations['channel_index'],
                left_sweep=n_pre*(-1),
                n_pre=n_pre,
                n_post=n_post)
            seg.spiketrains.append(st)

            print len(st)



            if waveforms and len(ids):
                wfs = np.zeros((n_post - n_pre,len(ids))) * anasig.units
                for i, id in enumerate(ids):
                    try:
                        wfs[:,i] = anasig[id+n_pre:id+n_post]
                    except:
                        pass
                if alignment=='min':
                    minima = np.min(wfs,axis=0)
                    wfs = wfs - minima[np.newaxis,:]
                else:
                    raise ValueError('Unknown aligmnment "%s"'%alignment)
                st.waveforms = wfs.T


            # connecting unit and segment
            rcgs = anasig.recordingchannel.recordingchannelgroups
            u_annotations = {'sorted': False,
                             'parameters': {'extraction_dict':extraction_dict}}

            new_unit = None
            for rcg in rcgs:
                # checking if a similar unit already exists (eg. from sorting a different segment)
                rcg_units = [u for u in rcg.units if u.name == st.name and u.annotations == u_annotations]
                if len(rcg_units) == 1:
                    unit = rcg_units[0]
                elif len(rcg_units) == 0:
                    # Generating new unit if necessary
                    if new_unit is None:
                        new_unit = neo.core.Unit(name=st.name, **u_annotations)
                    unit = new_unit
                else:
                    raise ValueError('%i units of name %s and annotations %s exists.'
                                     ' This is ambiguous.' % (len(rcg_units), st.name, u_annotations))
                rcg.units.append(unit)
                unit.spiketrains.append(st)










########################################################################################################################
def generate_spiketrains(block, software, waveforms=True, sort=True, parameter_dict={}):

    if software == 'phy':
        phy_parameters = get_updated_parameters(software=software,new_parameters=parameter_dict)
        generate_spiketrains_from_phy(block, waveforms=waveforms, sort=sort,parameter_dict=phy_parameters)

    elif software == 'spikesort':
        spikesort_parameters = get_updated_parameters(software=software,new_parameters=parameter_dict)
        extraction_dict = spikesort_parameters['extraction_dict']
        sorting_dict = spikesort_parameters['sorting_dict']
        generate_spiketrains_from_spikesort(block, waveforms=waveforms, sort=sort, extraction_dict=extraction_dict, sorting_dict=sorting_dict)

    elif software == 'manual':
        manual_parameters = get_updated_parameters(software=software,
                                                   new_parameters=parameter_dict)
        extraction_dict = manual_parameters['extraction_dict']
        generate_spiketrains_unsorted(block, waveforms=waveforms,
                                      extraction_dict=extraction_dict)






