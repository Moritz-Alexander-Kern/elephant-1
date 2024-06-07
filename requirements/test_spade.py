import numpy as np
import quantities as pq
import neo
import elephant
np.random.seed(4542)

spiketrains = elephant.spike_train_generation.compound_poisson_process(
   rate=5*pq.Hz, amplitude_distribution=[0]+[0.98]+[0]*8+[0.02], t_stop=10*pq.s)
print(len(spiketrains))

for i in range(90):
    spiketrains.append(elephant.spike_train_generation.homogeneous_poisson_process(
        rate=5*pq.Hz, t_stop=10*pq.s))
    
patterns = elephant.spade.spade(
    spiketrains=spiketrains, binsize=1*pq.ms, winlen=1, min_spikes=3,
    n_surr=100,dither=5*pq.ms,
    psr_param=[0,0,0],
    output_format='patterns')['patterns']

print(patterns)