"""Exports HDF5 PicoScope 7 synthétiques (tests)."""
import h5py
import numpy as np


def pico_h5(path, waveforms, unit="s", attrs_unit="V"):
    """
    Export au format PicoScope 7 : un groupe par voie, un dataset float32 par forme
    d'onde, /Abscissa (Path, StartValue, Interval) avec l'attribut AbscissaUnit.
    waveforms : {voie: [(valeurs, début, intervalle), ...]}
    """
    rows = []
    with h5py.File(path, "w") as h5:
        h5.attrs["Version"] = "7.2.30.10560"
        for channel, items in waveforms.items():
            group = h5.create_group(channel)
            for k, (values, start, step) in enumerate(items):
                ds = group.create_dataset(str(k + 1), data=np.asarray(values, np.float32))
                if attrs_unit:
                    ds.attrs["Unit"] = attrs_unit
                rows.append((f"/{channel}/{k + 1}", start, step))
        dtype = np.dtype([("Path", h5py.string_dtype()), ("StartValue", "<f8"),
                          ("Interval", "<f8")])
        table = np.array(rows, dtype=dtype)
        ab = h5.create_dataset("Abscissa", data=table)
        ab.attrs["AbscissaUnit"] = unit
    return str(path)


def attrs_h5(path, channels, epoch=1.7e9):
    """Variante : datasets à attributs start (s depuis 1970) et interval."""
    with h5py.File(path, "w") as h5:
        for name, (values, start, step) in channels.items():
            ds = h5.create_dataset(name, data=np.asarray(values, np.float32))
            ds.attrs["start"] = np.array([epoch + start])
            ds.attrs["interval"] = np.array([step])
    return str(path)
