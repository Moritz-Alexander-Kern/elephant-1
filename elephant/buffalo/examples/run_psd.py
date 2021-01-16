import numpy as np
import quantities as pq

from elephant.buffalo.examples.utils import get_analog_signal
from elephant.buffalo.objects.base import AnalysisObject
from elephant.spectral import welch_psd

import elephant.buffalo
import elephant.buffalo.provenance as provenance

import matplotlib.pyplot as plt

from numpy import mean

welch_psd = provenance.Provenance(inputs=['signal'])(welch_psd)
mean = provenance.Provenance(inputs=['a'])(mean)


@provenance.Provenance(inputs=['axes', 'freqs', 'psd'])
def plot_lfp_psd(axes, freqs, psd, label, freq_range=None, **kwargs):
    if freq_range is None:
        freq_range = [0, np.max(freqs)]

    indexes = np.where((freqs >= freq_range[0]) & (freqs <= freq_range[1]))

    axes.semilogy(freqs[indexes], psd[indexes], **kwargs)
    axes.set_ylabel(label)
    axes.set_xlabel(f"Frequency [{freqs.dimensionality}]")


def main():

    provenance.activate()

    elephant.buffalo.USE_ANALYSIS_OBJECTS = True

    signal = get_analog_signal(frequency=30*pq.Hz, n_channels=5, t_stop=3*pq.s,
                               sampling_rate=30000*pq.Hz, amplitude=50*pq.uV)

    #freqs, psd = welch_psd(signal)
    obj = welch_psd(signal)
    if isinstance(obj, AnalysisObject):
        print(obj.params)

    freqs, psd = obj
    avg_psd = mean(psd, axis=0)

    fig, axes = plt.subplots()
    plot_lfp_psd(axes, freqs, avg_psd, 'AnalysisObject', freq_range=[0,49])

    provenance.save_graph("psd_plot.html", show=True)

    plt.show()


if __name__ == "__main__":
    main()
