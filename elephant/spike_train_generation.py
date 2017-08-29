# -*- coding: utf-8 -*-
"""
Functions to generate spike trains from analog signals, or to generate random
spike trains.

Some functions are based on the NeuroTools stgen module, which was mostly
written by Eilif Muller, or from the NeuroTools signals.analogs module.

:copyright: Copyright 2015 by the Elephant team, see AUTHORS.txt.
:license: Modified BSD, see LICENSE.txt for details.
"""

from __future__ import division
import numpy as np
import quantities as pq
from quantities import ms, mV, Hz, Quantity, dimensionless
from neo import SpikeTrain
import random
from elephant.spike_train_surrogates import dither_spike_train
import warnings


def spike_extraction(signal, threshold=0.0 * mV, sign='above', detection='peak',
                     time_stamps=None, extr_interval=(-2 * ms, 4 * ms)):
    """
    Return a list of spiketrains containing the peak times of each channel of
    signal. Usually used for extracting spikes from a membrane
    potential to calculate waveform properties.

    Parameters
    ----------
    signal : neo AnalogSignal object
        'signal' is a neo analog signal.
    threshold : A quantity, e.g. in mV
        'threshold' contains a value that must be reached for an event
        to be detected. Default: 0.0 * mV.
    sign : 'above' or 'below'
        'sign' determines whether to count thresholding crossings
        that cross above or below the threshold. Default: 'above'.
    detection : 'peak' or 'treshold'. Extract peaks of signals or threshold
        crossing at spike time.
    time_stamps: None, quantity array or Object with .times interface
        if 'spike_train' is a quantity array or exposes a quantity array
        exposes the .times interface, it provides the time_stamps
        around which the waveform is extracted. If it is None, the
        function peak_detection is used to calculate the time_stamps
        from signal. Default: None.
    extr_interval: unpackable time quantities, len == 2
        'extr_interval' specifies the time interval around the
        time_stamps where the waveform is extracted. The default is an
        interval of '6 ms'. Default: (-2 * ms, 4 * ms).


    Returns
    -------
    result_st : list of neo SpikeTrain objects
        'result_st' contains the time_stamps of each of the spikes and
        the waveforms in result_st.waveforms. Waveforms of spikes that exceed
        the intervals contain None as samples.
    """
    # Get spike time_stamps
    if time_stamps is None:
        if detection == 'peak':
            spiketrains = peak_detection(signal, threshold, sign=sign)
        elif detection == 'threshold':
            spiketrains = threshold_detection(signal, threshold, sign=sign)
        else:
            raise ValueError("'detection' can only be 'peak' or 'threshold', "
                             "not {}".format(detection))
    elif hasattr(time_stamps, 'times'):
        times = time_stamps.times
        spiketrains = [SpikeTrain(times, units=signal.times.units,
                                  t_start=signal.t_start, t_stop=signal.t_stop,
                                  waveforms=np.array([]),
                                  sampling_rate=signal.sampling_rate)]
    elif type(time_stamps) is Quantity:
        times = time_stamps
    else:
        raise TypeError("time_stamps must be None, a quantity array or" +
                        " expose the.times interface")

    waveform_extraction(signal, spiketrains, extr_interval=extr_interval)

    return spiketrains

def waveform_extraction(signal, spiketrains, extr_interval=(-2 * ms, 4 * ms)):
    """
    Extract waveforms for each spiketrain by slicing the analogsignal around
    spike times and attaching slices to the corresponding spiketrain. In case of
     incomplete waveforms (too short analogsignal or to large extraction
     interval) the corresponding waveform is invalidated by filling it with 0.
     The annotations 'invalid_waveforms' contains the ids of invalidated
     spike waveforms.

    Parameters
    ----------
    signal : neo AnalogSignal object
        'signal' is a neo analog signal. If the signals contains only a
        single signal trace, then this will be duplicated for each
        spiketrain. If the number of signal traces matches the number of
        spiketrains a one-to-one mapping will be performed.
    spiketrains : list of spiketrains for which to extract waveforms. The
        waveforms
    extr_interval: unpackable time quantities, len == 2
        'extr_interval' specifies the time interval around the
        time_stamps where the waveform is extracted. The default is an
        interval of '6 ms'. Default: (-2 * ms, 4 * ms).

    Returns
    -------
    None
    """
    n_anasigs = signal.shape[-1]
    if (n_anasigs != len(spiketrains)) and (n_anasigs != 1):
        raise ValueError('AnalogSignal needs to contain either 1 or {} '
                         'signals, not {}'.format(len(spiketrains), n_anasigs))

    for st_id, st in enumerate(spiketrains):
        if n_anasigs == 1:
            anasig = signal
        else:
            anasig = signal[:, st_id]

        expected_wf_length = np.ceil(((extr_interval[1] - extr_interval[0])
                                      * anasig.sampling_rate).
                                     rescale('dimensionless'))
        expected_wf_length = int(expected_wf_length)
        waveforms = []
        invalid_waveforms = []
        for st_id, spiketime in enumerate(st):
            invalid_wf = False
            t_start = spiketime + extr_interval[0]
            t_stop = spiketime + extr_interval[1]
            # alternative implementation instead of if-else clause here:
            # try-catch statement, since time_slice raises ValueError
            if t_start < anasig.t_start or t_stop > anasig.t_stop:
                wf = np.full((expected_wf_length), 0)
                invalid_wf = True
            else:
                wf = anasig.time_slice(t_start, t_stop).magnitude[:, 0]
            if len(wf) != expected_wf_length:
                wf = np.full((expected_wf_length), 0)
                invalid_wf = True
            if invalid_wf:
                invalid_waveforms.append(st_id)

            waveforms.append(wf)
        waveforms = np.asarray(waveforms)

        # extending dimensions for potential tetrode waveform recordings

        if len(waveforms) == 0:
            waveforms = np.array([]).reshape((0,0))
        waveforms = waveforms[:, np.newaxis, :]

        waveforms = np.array(waveforms) * anasig.units

        st.waveforms = waveforms
        st.annotate(invalid_waveforms=invalid_waveforms)
        st.left_sweep = extr_interval[0]

        if (np.diff(st.magnitude, axis=0) * st.units <
                    extr_interval[0] - extr_interval[1]).any():
            warnings.warn("Waveforms overlap.", UserWarning)


def threshold_detection(signal, threshold=1, sign='above'):
    """
    Returns the times when the analog signal crosses a threshold.
    Usually used for extracting spike times from a membrane potential.
    Adapted from version in NeuroTools.

    Parameters
    ----------
    signal : neo AnalogSignal object
        'signal' is an analog signal.
    threshold : float, integer or quantity, e.g. in mV
        'threshold' contains a value that must be reached
        for an event to be detected. Default: 1
    sign : 'above' or 'below'
        'sign' determines whether to count thresholding crossings
        that cross above or below the threshold.

    Returns
    -------
    result_sts : list of neo SpikeTrain objects
        Each spiketrain in 'result_st' contains the spike times of each of the
        events (spikes) extracted from the corresponding signal trace.
        The ordering of the spiketrains corresponds to the signal traces in
        the analogsignal.
    """

    assert threshold is not None, "A threshold must be provided"

    if isinstance(threshold, Quantity):
        signal.rescale(threshold.units)
    elif isinstance(threshold, (int, float)):
        threshold = np.std(signal, axis=0)[np.newaxis, :] * threshold
    else:
        raise ValueError('Threshold needs to be number or quantity, not of '
                         'type {}'.format(type(threshold)))

    if sign is 'above':
        # artificially swapping signal axis to directly get results sorted in
        #  second (channel_id) dimension and not in time dimension
        cutout = np.asarray(np.where(signal.T > threshold.T))[::-1]
    elif sign in 'below':
        cutout = np.asarray(np.where(signal.T < threshold.T))[::-1]

    result_sts = []

    times = signal.times
    borders = _get_border_ids_multi_channel(cutout[0],
                                            channel_ids=cutout[1],
                                            sample_scale=2)

    # generating one spiketrain per channel
    for channel_id in range(signal.shape[-1]):
        if channel_id not in borders:
            events_base = []
        else:
            left_borders = borders[channel_id][0::2]

            events = times[left_borders]

            events_base = events.base
            if events_base is None:
                # This occurs in some Python 3 builds due to some
                # bug in quantities.
                events_base = np.array(
                        [event.base for event in events])  # Workaround

        result_sts.append(SpikeTrain(events_base,
                                     units=signal.times.units,
                                     t_start=signal.t_start,
                                     t_stop=signal.t_stop,
                                     sampling_rate=signal.sampling_rate))

    return result_sts


def peak_detection(signal, threshold=0.0 * mV, sign='above'):
    """
    Return the peak times for all events that cross threshold.
    Usually used for extracting spike times from a membrane potential.
    Similar to spike_train_generation.threshold_detection.

    Parameters
    ----------
    signal : neo AnalogSignal object
        'signal' is an analog signal.
    threshold : A quantity, e.g. in mV
        'threshold' contains a value that must be reached
        for an event to be detected.
    sign : 'above' or 'below'
        'sign' determines whether to count thresholding crossings that
        cross above or below the threshold. Default: 'above'.

    Returns
    -------
    result_sts : list of neo SpikeTrain objects
        Each spiketrain in 'result_st' contains the spike times of each of the
        events (spikes) extracted from the corresponding signal trace.
        The ordering of the spiketrains corresponds to the signal traces in
        the analogsignal.
    """
    assert threshold is not None, "A threshold must be provided"

    if isinstance(threshold, Quantity):
        signal.rescale(threshold.units)
    elif isinstance(threshold, (int, float)):
        threshold = np.std(signal, axis=0)[np.newaxis, :] * threshold
    else:
        raise ValueError('Threshold needs to be number or quantity, not of '
                         'type {}'.format(type(threshold)))

    if sign is 'above':
        # artificially swapping signal axis to directly get results sorted in
        #  second (channel_id) dimension and not in time dimension
        cutout = np.asarray(np.where(signal.T > threshold.T))[::-1]
        peak_func = lambda x: np.argmax(x, axis=0)
    elif sign in 'below':
        cutout = np.asarray(np.where(signal.T < threshold.T))[::-1]
        peak_func = lambda x: np.argmin(x, axis=0)
    else:
        raise ValueError("sign must be 'above' or 'below'")

    result_sts = []

    border_set_ids = _get_border_ids_multi_channel(cutout[0],
                                                   cutout[1],
                                                   sample_scale=2)
    for channel_id in range(signal.shape[-1]):
        if channel_id not in border_set_ids:
            events_base = []
        else:
            true_borders = border_set_ids[channel_id]

            split_signal = np.split(signal[:, channel_id], true_borders)[1::2]

            maxima_idc_split = np.array([peak_func(x) for x in split_signal])

            max_idc = maxima_idc_split + true_borders[0::2, np.newaxis]

            events = signal.times[max_idc]
            # spike trains are 1D in contrast to analogsignals
            events = events.flatten()
            events_base = events.base

            if events_base is None:
                # This occurs in some Python 3 builds due to some
                # bug in quantities.
                events_base = np.array(
                        [event.base for event in events])  # Workaround

        result_sts.append(
                SpikeTrain(events_base,
                           units=signal.times.units,
                           t_start=signal.t_start,
                           t_stop=signal.t_stop,
                           sampling_rate=signal.sampling_rate))

    return result_sts


def _get_border_ids_multi_channel(cutout_times, channel_ids=None,
                                  sample_scale=1):
    '''
    Get border ids of sequences, which only contain gaps smaller or equal to
    the ignored_id_gap_size.
    IMPORTANT: Sequences of length 1 will be ignored!

    Parameters
    ----------
    cutout_times : array containing ids.
    cutout_channels : None or array of same length as cutout_times,
        defining the corresponding recording channels after which to
        sort the ids. Default: None
    sample_scale : int, scale on which gaps in subsequent ids will be
        ignored

    Returns
    -------
    dictionary containing the border ids (value) for each channel_id (key)

    '''

    # generating channel array as if all timestamps belong to channel 0
    if channel_ids is None:
        channels = np.full(cutout_times.shape, 0)
    else:
        channels = channel_ids

    result = {}
    for channel_id in np.sort(np.unique(channels)):
        channel_condition = (channels == channel_id)

        cutout_times_i = cutout_times[channel_condition]
        border_ids_i = _get_border_ids(cutout_times_i,
                                       sample_scale=sample_scale)
        if channel_ids is None:
            channel_id = None
        result[channel_id] = border_ids_i
    return result


def _get_border_ids(cutout, sample_scale=1):
    '''
    Get border ids of sequences, which only contain gaps smaller or equal to
    the ignored_id_gap_size.
    IMPORTANT: Sequences of length 1 will be ignored!

    Parameters
    ----------
    cutout : array containing ids.
    sample_scale : int, scale on which gaps in subsequent ids will be
        ignored

    Returns
    -------
    array containing the border ids
    '''
    if len(cutout.shape) > 1:
        raise ValueError('_get_border_ids can not handle multi dimensional '
                         'cutout segments. '
                         'Please use "_get_border_ids_multi_channel" instead.')
    elif len(cutout) <= 0:
        return np.array([])

    # Select threshold crossings ignoring gaps up to the range of sample_scale
    border_start = np.where(np.diff(cutout) > sample_scale)[0]
    border_end = border_start + 1
    # storing border values as
    # [segment1_start, segment1_stop, segment2_start, segment2_stop, ...]
    borders = np.insert(border_start, np.arange(len(border_end)) + 1,
                        border_end)
    # extending to border ids to full range of cutout to cover all segments
    borders = np.concatenate(([0], borders, [len(cutout) - 1]))
    true_borders = cutout[borders]
    # shift right borders by 1, because slicing does not include element at
    # stop id
    right_borders = true_borders[1::2] + 1
    true_borders = np.sort(np.append(true_borders[0::2], right_borders))
    return true_borders


def _homogeneous_process(interval_generator, args, mean_rate, t_start, t_stop,
                         as_array):
    """
    Returns a spike train whose spikes are a realization of a random process
    generated by the function `interval_generator` with the given rate,
    starting at time `t_start` and stopping `time t_stop`.
    """

    def rescale(x):
        return (x / mean_rate.units).rescale(t_stop.units)

    n = int(((t_stop - t_start) * mean_rate).simplified)
    number = np.ceil(n + 3 * np.sqrt(n))
    if number < 100:
        number = min(5 + np.ceil(2 * n), 100)
    assert number > 4  # if positive, number cannot be less than 5
    isi = rescale(interval_generator(*args, size=int(number)))
    spikes = np.cumsum(isi)
    spikes += t_start

    i = spikes.searchsorted(t_stop)
    if i == len(spikes):
        # ISI buffer overrun
        extra_spikes = []
        t_last = spikes[-1] + rescale(interval_generator(*args, size=1))[0]
        while t_last < t_stop:
            extra_spikes.append(t_last)
            t_last = t_last + rescale(interval_generator(*args, size=1))[0]
        # np.concatenate does not conserve units
        spikes = Quantity(
                np.concatenate(
                        (spikes, extra_spikes)).magnitude, units=spikes.units)
    else:
        spikes = spikes[:i]

    if as_array:
        spikes = spikes.magnitude
    else:
        spikes = SpikeTrain(
                spikes, t_start=t_start, t_stop=t_stop, units=spikes.units)

    return spikes


def homogeneous_poisson_process(rate, t_start=0.0 * ms, t_stop=1000.0 * ms,
                                as_array=False):
    """
    Returns a spike train whose spikes are a realization of a Poisson process
    with the given rate, starting at time `t_start` and stopping time `t_stop`.

    All numerical values should be given as Quantities, e.g. 100*Hz.

    Parameters
    ----------

    rate : Quantity scalar with dimension 1/time
           The rate of the discharge.
    t_start : Quantity scalar with dimension time
              The beginning of the spike train.
    t_stop : Quantity scalar with dimension time
             The end of the spike train.
    as_array : bool
               If True, a NumPy array of sorted spikes is returned,
               rather than a SpikeTrain object.

    Raises
    ------
    ValueError : If `t_start` and `t_stop` are not of type `pq.Quantity`.

    Examples
    --------
        >>> from quantities import Hz, ms
        >>> spikes = homogeneous_poisson_process(50*Hz, 0*ms, 1000*ms)
        >>> spikes = homogeneous_poisson_process(
            20*Hz, 5000*ms, 10000*ms, as_array=True)

    """
    if not isinstance(t_start, Quantity) or not isinstance(t_stop, Quantity):
        raise ValueError("t_start and t_stop must be of type pq.Quantity")
    rate = rate.rescale((1 / t_start).units)
    mean_interval = 1 / rate.magnitude
    return _homogeneous_process(
            np.random.exponential, (mean_interval,), rate, t_start, t_stop,
            as_array)


def homogeneous_gamma_process(a, b, t_start=0.0 * ms, t_stop=1000.0 * ms,
                              as_array=False):
    """
    Returns a spike train whose spikes are a realization of a gamma process
    with the given parameters, starting at time `t_start` and stopping time
    `t_stop` (average rate will be b/a).

    All numerical values should be given as Quantities, e.g. 100*Hz.

    Parameters
    ----------

    a : int or float
        The shape parameter of the gamma distribution.
    b : Quantity scalar with dimension 1/time
        The rate parameter of the gamma distribution.
    t_start : Quantity scalar with dimension time
              The beginning of the spike train.
    t_stop : Quantity scalar with dimension time
             The end of the spike train.
    as_array : bool
               If True, a NumPy array of sorted spikes is returned,
               rather than a SpikeTrain object.

    Raises
    ------
    ValueError : If `t_start` and `t_stop` are not of type `pq.Quantity`.

    Examples
    --------
        >>> from quantities import Hz, ms
        >>> spikes = homogeneous_gamma_process(2.0, 50*Hz, 0*ms, 1000*ms)
        >>> spikes = homogeneous_gamma_process(
                5.0, 20*Hz, 5000*ms, 10000*ms, as_array=True)

    """
    if not isinstance(t_start, Quantity) or not isinstance(t_stop, Quantity):
        raise ValueError("t_start and t_stop must be of type pq.Quantity")
    b = b.rescale((1 / t_start).units).simplified
    rate = b / a
    k, theta = a, (1 / b.magnitude)
    return _homogeneous_process(np.random.gamma, (k, theta), rate, t_start,
                                t_stop, as_array)


def _n_poisson(rate, t_stop, t_start=0.0 * ms, n=1):
    """
    Generates one or more independent Poisson spike trains.

    Parameters
    ----------
    rate : Quantity or Quantity array
        Expected firing rate (frequency) of each output SpikeTrain.
        Can be one of:
        *  a single Quantity value: expected firing rate of each output
           SpikeTrain
        *  a Quantity array: rate[i] is the expected firing rate of the i-th
           output SpikeTrain
    t_stop : Quantity
        Single common stop time of each output SpikeTrain. Must be > t_start.
    t_start : Quantity (optional)
        Single common start time of each output SpikeTrain. Must be < t_stop.
        Default: 0 s.
    n: int (optional)
        If rate is a single Quantity value, n specifies the number of
        SpikeTrains to be generated. If rate is an array, n is ignored and the
        number of SpikeTrains is equal to len(rate).
        Default: 1


    Returns
    -------
    list of neo.SpikeTrain
        Each SpikeTrain contains one of the independent Poisson spike trains,
        either n SpikeTrains of the same rate, or len(rate) SpikeTrains with
        varying rates according to the rate parameter. The time unit of the
        SpikeTrains is given by t_stop.
    """
    # Check that the provided input is Hertz of return error
    try:
        for r in rate.reshape(-1, 1):
            r.rescale('Hz')
    except AttributeError:
        raise ValueError('rate argument must have rate unit (1/time)')

    # Check t_start < t_stop and create their strip dimensions
    if not t_start < t_stop:
        raise ValueError(
                't_start (={}) must be < t_stop (={})'.format(t_start, t_stop))

    # Set number n of output spike trains (specified or set to len(rate))
    if not (type(n) == int and n > 0):
        raise ValueError('n (={}) must be a positive integer'.format(str(n)))
    rate_dl = rate.simplified.magnitude.flatten()

    # Check rate input parameter
    if len(rate_dl) == 1:
        if rate_dl < 0:
            raise ValueError('rate (={}) must be non-negative.'.format(rate))
        rates = np.array([rate_dl] * n)
    else:
        rates = rate_dl.flatten()
        if any(rates < 0):
            raise ValueError('rate must have non-negative elements.')
    sts = []
    for r in rates:
        sts.append(homogeneous_poisson_process(r * Hz, t_start, t_stop))
    return sts


def single_interaction_process(
        rate, rate_c, t_stop, n=2, jitter=0 * ms, coincidences='deterministic',
        t_start=0 * ms, min_delay=0 * ms, return_coinc=False):
    """
    Generates a multidimensional Poisson SIP (single interaction process)
    plus independent Poisson processes

    A Poisson SIP consists of Poisson time series which are independent
    except for simultaneous events in all of them. This routine generates
    a SIP plus additional parallel independent Poisson processes.

    See [1].

    Parameters
    -----------
    t_stop: quantities.Quantity
        Total time of the simulated processes. The events are drawn between
        0 and `t_stop`.
    rate: quantities.Quantity
        Overall mean rate of the time series to be generated (coincidence
        rate `rate_c` is subtracted to determine the background rate). Can be:
        * a float, representing the overall mean rate of each process. If
          so, it must be higher than `rate_c`.
        * an iterable of floats (one float per process), each float
          representing the overall mean rate of a process. If so, all the
          entries must be larger than `rate_c`.
    rate_c: quantities.Quantity
        Coincidence rate (rate of coincidences for the n-dimensional SIP).
        The SIP spike trains will have coincident events with rate `rate_c`
        plus independent 'background' events with rate `rate-rate_c`.
    n: int, optional
        If `rate` is a single Quantity value, `n` specifies the number of
        SpikeTrains to be generated. If rate is an array, `n` is ignored and
        the number of SpikeTrains is equal to `len(rate)`.
        Default: 1
    jitter: quantities.Quantity, optional
        Jitter for the coincident events. If `jitter == 0`, the events of all
        n correlated processes are exactly coincident. Otherwise, they are
        jittered around a common time randomly, up to +/- `jitter`.
    coincidences: string, optional
        Whether the total number of injected coincidences must be determin-
        istic (i.e. rate_c is the actual rate with which coincidences are
        generated) or stochastic (i.e. rate_c is the mean rate of coincid-
        ences):
        * 'deterministic': deterministic rate
        * 'stochastic': stochastic rate
        Default: 'deterministic'
    t_start: quantities.Quantity, optional
        Starting time of the series. If specified, it must be lower than
        t_stop
        Default: 0 * ms
    min_delay: quantities.Quantity, optional
        Minimum delay between consecutive coincidence times.
        Default: 0 * ms
    return_coinc: bool, optional
        Whether to return the coincidence times for the SIP process
        Default: False


    Returns
    --------
    output: list
        Realization of a SIP consisting of n Poisson processes characterized
        by synchronous events (with the given jitter)
        If `return_coinc` is `True`, the coincidence times are returned as a
        second output argument. They also have an associated time unit (same
        as `t_stop`).

    References
    ----------
    [1] Kuhn, Aertsen, Rotter (2003) Neural Comput 15(1):67-101

    *************************************************************************
    """

    # Check if n is a positive integer
    if not (isinstance(n, int) and n > 0):
        raise ValueError('n (={}) must be a positive integer'.format(str(n)))

    # Assign time unit to jitter, or check that its existing unit is a time
    # unit
    jitter = abs(jitter)

    # Define the array of rates from input argument rate. Check that its length
    # matches with n
    if rate.ndim == 0:
        if rate < 0 * Hz:
            raise ValueError(
                    'rate (={}) must be non-negative.'.format(str(rate)))
        rates_b = np.array(
                [rate.magnitude for _ in range(n)]) * rate.units
    else:
        rates_b = np.array(rate).flatten() * rate.units
        if not all(rates_b >= 0. * Hz):
            raise ValueError('*rate* must have non-negative elements')

    # Check: rate>=rate_c
    if np.any(rates_b < rate_c):
        raise ValueError('all elements of *rate* must be >= *rate_c*')

    # Check min_delay < 1./rate_c
    if not (rate_c == 0 * Hz or min_delay < 1. / rate_c):
        raise ValueError(
                "'*min_delay* ({}) must be lower than 1/*rate_c* ({})."
                    .format(str(min_delay),
                            str((1. / rate_c).rescale(min_delay.units))))

    # Generate the n Poisson processes there are the basis for the SIP
    # (coincidences still lacking)
    embedded_poisson_trains = _n_poisson(
            rate=rates_b - rate_c, t_stop=t_stop, t_start=t_start)
    # Convert the trains from neo SpikeTrain objects to simpler Quantity
    # objects
    embedded_poisson_trains = [
        emb.view(Quantity) for emb in embedded_poisson_trains]

    # Generate the array of times for coincident events in SIP, not closer than
    # min_delay. The array is generated as a quantity from the Quantity class
    # in the quantities module
    if coincidences == 'deterministic':
        Nr_coinc = int(((t_stop - t_start) * rate_c).rescale(dimensionless))
        while True:
            coinc_times = t_start + \
                          np.sort(np.random.random(Nr_coinc)) * (
                              t_stop - t_start)
            if len(coinc_times) < 2 or min(np.diff(coinc_times)) >= min_delay:
                break
    elif coincidences == 'stochastic':
        while True:
            coinc_times = homogeneous_poisson_process(
                    rate=rate_c, t_stop=t_stop, t_start=t_start)
            if len(coinc_times) < 2 or min(np.diff(coinc_times)) >= min_delay:
                break
        # Convert coinc_times from a neo SpikeTrain object to a Quantity object
        # pq.Quantity(coinc_times.base)*coinc_times.units
        coinc_times = coinc_times.view(Quantity)
        # Set the coincidence times to T-jitter if larger. This ensures that
        # the last jittered spike time is <T
        for i in range(len(coinc_times)):
            if coinc_times[i] > t_stop - jitter:
                coinc_times[i] = t_stop - jitter

    # Replicate coinc_times n times, and jitter each event in each array by
    # +/- jitter (within (t_start, t_stop))
    embedded_coinc = coinc_times + \
                     np.random.random(
                             (len(rates_b),
                              len(coinc_times))) * 2 * jitter - jitter
    embedded_coinc = embedded_coinc + \
                     (t_start - embedded_coinc) * (embedded_coinc < t_start) - \
                     (t_stop - embedded_coinc) * (embedded_coinc > t_stop)

    # Inject coincident events into the n SIP processes generated above, and
    # merge with the n independent processes
    sip_process = [
        np.sort(np.concatenate((
            embedded_poisson_trains[m].rescale(t_stop.units),
            embedded_coinc[m].rescale(t_stop.units))) * t_stop.units)
        for m in range(len(rates_b))]

    # Convert back sip_process and coinc_times from Quantity objects to
    # neo.SpikeTrain objects
    sip_process = [
        SpikeTrain(t, t_start=t_start, t_stop=t_stop).rescale(t_stop.units)
        for t in sip_process]
    coinc_times = [
        SpikeTrain(t, t_start=t_start, t_stop=t_stop).rescale(t_stop.units)
        for t in embedded_coinc]

    # Return the processes in the specified output_format
    if not return_coinc:
        output = sip_process
    else:
        output = sip_process, coinc_times

    return output


def _pool_two_spiketrains(a, b, extremes='inner'):
    """
    Pool the spikes of two spike trains a and b into a unique spike train.

    Parameters
    ----------
    a, b : neo.SpikeTrains
        Spike trains to be pooled

    extremes: str, optional
        Only spikes of a and b in the specified extremes are considered.
        * 'inner': pool all spikes from max(a.tstart_ b.t_start) to
           min(a.t_stop, b.t_stop)
        * 'outer': pool all spikes from min(a.tstart_ b.t_start) to
           max(a.t_stop, b.t_stop)
        Default: 'inner'

    Output
    ------
    neo.SpikeTrain containing all spikes in a and b falling in the
    specified extremes
    """

    unit = a.units
    times_a_dimless = list(a.view(Quantity).magnitude)
    times_b_dimless = list(b.rescale(unit).view(Quantity).magnitude)
    times = (times_a_dimless + times_b_dimless) * unit

    if extremes == 'outer':
        t_start = min(a.t_start, b.t_start)
        t_stop = max(a.t_stop, b.t_stop)
    elif extremes == 'inner':
        t_start = max(a.t_start, b.t_start)
        t_stop = min(a.t_stop, b.t_stop)
        times = times[times > t_start]
        times = times[times < t_stop]

    else:
        raise ValueError(
                'extremes ({}) can only be "inner" or "outer"'.format(extremes))
    pooled_train = SpikeTrain(
            times=sorted(times.magnitude), units=unit, t_start=t_start,
            t_stop=t_stop)
    return pooled_train


def _pool_spiketrains(trains, extremes='inner'):
    """
    Pool spikes from any number of spike trains into a unique spike train.

    Parameters
    ----------
    trains: list
        list of spike trains to merge

    extremes: str, optional
        Only spikes of a and b in the specified extremes are considered.
        * 'inner': pool all spikes from min(a.t_start b.t_start) to
           max(a.t_stop, b.t_stop)
        * 'outer': pool all spikes from max(a.tstart_ b.t_start) to
           min(a.t_stop, b.t_stop)
        Default: 'inner'

    Output
    ------
    neo.SpikeTrain containing all spikes in trains falling in the
    specified extremes
    """

    merge_trains = trains[0]
    for t in trains[1:]:
        merge_trains = _pool_two_spiketrains(
                merge_trains, t, extremes=extremes)
    t_start, t_stop = merge_trains.t_start, merge_trains.t_stop
    merge_trains = sorted(merge_trains)
    merge_trains = np.squeeze(merge_trains)
    merge_trains = SpikeTrain(
            merge_trains, t_stop=t_stop, t_start=t_start, units=trains[0].units)
    return merge_trains


def _sample_int_from_pdf(a, n):
    """
    Draw n independent samples from the set {0,1,...,L}, where L=len(a)-1,
    according to the probability distribution a.
    a[j] is the probability to sample j, for each j from 0 to L.


    Parameters
    -----
    a: numpy.array
        Probability vector (i..e array of sum 1) that at each entry j carries
        the probability to sample j (j=0,1,...,len(a)-1).

    n: int
        Number of samples generated with the function

    Output
    -------
    array of n samples taking values between 0 and n=len(a)-1.
    """

    A = np.cumsum(a)  # cumulative distribution of a
    u = np.random.uniform(0, 1, size=n)
    U = np.array([u for i in a]).T  # copy u (as column vector) len(a) times
    return (A < U).sum(axis=1)


def _mother_proc_cpp_stat(A, t_stop, rate, t_start=0 * ms):
    """
    Generate the hidden ("mother") Poisson process for a Compound Poisson
    Process (CPP).


    Parameters
    ----------
    A : numpy.array
        Amplitude distribution. A[j] represents the probability of a
        synchronous event of size j.
        The sum over all entries of a must be equal to one.
    t_stop : quantities.Quantity
        The stopping time of the mother process
    rate : quantities.Quantity
        Homogeneous rate of the n spike trains that will be genereted by the
        CPP function
    t_start : quantities.Quantity, optional
        The starting time of the mother process
        Default: 0 ms

    Output
    ------
    Poisson spike train representing the mother process generating the CPP
    """
    N = len(A) - 1
    exp_A = np.dot(A, range(N + 1))  # expected value of a
    exp_mother = (N * rate) / float(exp_A)  # rate of the mother process
    return homogeneous_poisson_process(
            rate=exp_mother, t_stop=t_stop, t_start=t_start)


def _cpp_hom_stat(A, t_stop, rate, t_start=0 * ms):
    """
    Generate a Compound Poisson Process (CPP) with amplitude distribution
    A and heterogeneous firing rates r=r[0], r[1], ..., r[-1].

    Parameters
    ----------
    A : numpy.ndarray
        Amplitude distribution. A[j] represents the probability of a
        synchronous event of size j.
        The sum over all entries of A must be equal to one.
    t_stop : quantities.Quantity
        The end time of the output spike trains
    rate : quantities.Quantity
        Average rate of each spike train generated
    t_start : quantities.Quantity, optional
        The start time of the output spike trains
        Default: 0 ms

    Output
    ------
    List of n neo.SpikeTrains, having average firing rate r and correlated
    such to form a CPP with amplitude distribution a
    """

    # Generate mother process and associated spike labels
    mother = _mother_proc_cpp_stat(
            A=A, t_stop=t_stop, rate=rate, t_start=t_start)
    labels = _sample_int_from_pdf(A, len(mother))

    N = len(A) - 1  # Number of trains in output

    try:  # Faster but more memory-consuming approach
        M = len(mother)  # number of spikes in the mother process
        spike_matrix = np.zeros((N, M), dtype=bool)
        # for each spike, take its label l
        for spike_id, l in enumerate(labels):
            # choose l random trains
            train_ids = random.sample(range(N), l)
            # and set the spike matrix for that train
            for train_id in train_ids:
                spike_matrix[train_id, spike_id] = True  # and spike to True

        times = [[] for i in range(N)]
        for train_id, row in enumerate(spike_matrix):
            times[train_id] = mother[row].view(Quantity)

    except MemoryError:  # Slower (~2x) but less memory-consuming approach
        print('memory case')
        times = [[] for i in range(N)]
        for t, l in zip(mother, labels):
            train_ids = random.sample(range(N), l)
            for train_id in train_ids:
                times[train_id].append(t)

    trains = [SpikeTrain(
            times=t, t_start=t_start, t_stop=t_stop) for t in times]

    return trains


def _cpp_het_stat(A, t_stop, rate, t_start=0. * ms):
    """
    Generate a Compound Poisson Process (CPP) with amplitude distribution
    A and heterogeneous firing rates r=r[0], r[1], ..., r[-1].

    Parameters
    ----------
    A : array
        CPP's amplitude distribution. A[j] represents the probability of
        a synchronous event of size j among the generated spike trains.
        The sum over all entries of A must be equal to one.
    t_stop : Quantity (time)
        The end time of the output spike trains
    rate : Quantity (1/time)
        Average rate of each spike train generated
    t_start : quantities.Quantity, optional
        The start time of the output spike trains
        Default: 0 ms

    Output
    ------
    List of neo.SpikeTrains with different firing rates, forming
    a CPP with amplitude distribution A
    """

    # Computation of Parameters of the two CPPs that will be merged
    # (uncorrelated with heterog. rates + correlated with homog. rates)
    N = len(rate)  # number of output spike trains
    A_exp = np.dot(A, range(N + 1))  # expectation of A
    r_sum = np.sum(rate)  # sum of all output firing rates
    r_min = np.min(rate)  # minimum of the firing rates
    r1 = r_sum - N * r_min  # rate of the uncorrelated CPP
    r2 = r_sum / float(A_exp) - r1  # rate of the correlated CPP
    r_mother = r1 + r2  # rate of the hidden mother process

    # Check the analytical constraint for the amplitude distribution
    if A[1] < (r1 / r_mother).rescale(dimensionless).magnitude:
        raise ValueError('A[1] too small / A[i], i>1 too high')

    # Compute the amplitude distrib of the correlated CPP, and generate it
    a = [(r_mother * i) / float(r2) for i in A]
    a[1] = a[1] - r1 / float(r2)
    CPP = _cpp_hom_stat(a, t_stop, r_min, t_start)

    # Generate the independent heterogeneous Poisson processes
    POISS = [
        homogeneous_poisson_process(i - r_min, t_start, t_stop) for i in rate]

    # Pool the correlated CPP and the corresponding Poisson processes
    out = [_pool_two_spiketrains(CPP[i], POISS[i]) for i in range(N)]
    return out


def compound_poisson_process(rate, A, t_stop, shift=None, t_start=0 * ms):
    """
    Generate a Compound Poisson Process (CPP; see [1]) with a given amplitude
    distribution A and stationary marginal rates r.

    The CPP process is a model for parallel, correlated processes with Poisson
    spiking statistics at pre-defined firing rates. It is composed of len(A)-1
    spike trains with a correlation structure determined by the amplitude
    distribution A: A[j] is the probability that a spike occurs synchronously
    in any j spike trains.

    The CPP is generated by creating a hidden mother Poisson process, and then
    copying spikes of the mother process to j of the output spike trains with
    probability A[j].

    Note that this function decorrelates the firing rate of each SpikeTrain
    from the probability for that SpikeTrain to participate in a synchronous
    event (which is uniform across SpikeTrains).

    Parameters
    ----------
    rate : quantities.Quantity
        Average rate of each spike train generated. Can be:
          - a single value, all spike trains will have same rate rate
          - an array of values (of length len(A)-1), each indicating the
            firing rate of one process in output
    A : array
        CPP's amplitude distribution. A[j] represents the probability of
        a synchronous event of size j among the generated spike trains.
        The sum over all entries of A must be equal to one.
    t_stop : quantities.Quantity
        The end time of the output spike trains.
    shift : None or quantities.Quantity, optional
        If None, the injected synchrony is exact. If shift is a Quantity, all
        the spike trains are shifted independently by a random amount in
        the interval [-shift, +shift].
        Default: None
    t_start : quantities.Quantity, optional
        The t_start time of the output spike trains.
        Default: 0 s

    Returns
    -------
    List of neo.SpikeTrains
        SpikeTrains with specified firing rates forming the CPP with amplitude
        distribution A.

    References
    ----------
    [1] Staude, Rotter, Gruen (2010) J Comput Neurosci 29:327-350.
    """
    # Check A is a probability distribution (it sums to 1 and is positive)
    if abs(sum(A) - 1) > np.finfo('float').eps:
        raise ValueError(
                'A must be a probability vector, sum(A)= {} !=1'.format((sum(
                        A))))
    if any([a < 0 for a in A]):
        raise ValueError(
                'A must be a probability vector, all the elements of must be '
                '>0')
    # Check that the rate is not an empty Quantity
    if rate.ndim == 1 and len(rate.magnitude) == 0:
        raise ValueError('Rate is an empty Quantity array')
    # Return empty spike trains for specific parameters
    elif A[0] == 1 or np.sum(np.abs(rate.magnitude)) == 0:
        return [
            SpikeTrain([] * t_stop.units, t_stop=t_stop,
                       t_start=t_start) for i in range(len(A) - 1)]
    else:
        # Homogeneous rates
        if rate.ndim == 0:
            cpp = _cpp_hom_stat(A=A, t_stop=t_stop, rate=rate, t_start=t_start)
        # Heterogeneous rates
        else:
            cpp = _cpp_het_stat(A=A, t_stop=t_stop, rate=rate, t_start=t_start)

        if shift is None:
            return cpp
        # Dither the output spiketrains
        else:
            cpp = [
                dither_spike_train(cp, shift=shift, edges=True)[0]
                for cp in cpp]
            return cpp


# Alias for the compound poisson process
cpp = compound_poisson_process
