# Broadband N-port models with snp2le

The **Postprocessing → Broadband Model** sub-tab, next to Lumped models, uses
[snp2le](https://github.com/iic-jku/snp2le)'s
universal vector-fitting core. It fits the entire Touchstone network, including
all N ports, without needing GDS, a stackup or a simulation setup. Its model
elements reproduce terminal behavior and are not physical device parameters.
The physical inductor/MIM/RLGC tools remain under Postprocessing → Lumped models.

## Workflow

1. Browse to an `.sNp` file or **Use postprocessing file**, then Load. The header
   identifies the source, port count, frequency range and hash, and whether it
   contains a finite DC point.
2. Choose the fit band in GHz. Zero means the file start/end. The engine fits
   positive-frequency samples; at least four must lie in the band.
3. Set **Maximum order**: real poles plus twice complex pole pairs. The adaptive
   fit may use fewer; the result reports the actual order. Increasing it can
   improve agreement but also grows the model and can affect conditioning.
4. Choose passivity enforcement, optional thermal noise, the output subcircuit
   name and dialect. Advanced options expose the passivity ceiling, convex-refit
   state limit and DC correction parameters.
5. Check **Engine Python**, then **Fit broadband model in new folder**. Choose a
   parent directory. A new timestamped run folder stores an exact input snapshot,
   settings, outputs and diagnostics. The GUI stays responsive, reports progress
   and elapsed time, and offers Stop fit. It does not estimate time remaining.
6. Review the overall and per-response fit errors, passivity and DC-health reports.
   **Compare source / model** adds the normalized source snapshot and fitted result
   to Postprocessing → Plot and opens its separate comparison window. That view
   initially shows ports 1/2; choose other pairs there for larger networks. The fit
   itself always includes every port. Existing comparison entries are retained.

Fitting a file does not automatically mean that its error is acceptable. Inspect
the traces important to the circuit, and increase order or narrow the band where
needed. Per-response relative error is undefined if the source response has zero
RMS. Reported errors use native fit samples without smoothing or interpolation.
They do not establish accuracy outside the fitted band.

## Passivity, noise and DC

Strict passivity enforcement defaults on, with ceiling 1.0. A relaxed ceiling up
to 1.2 explicitly permits nonpassivity. The report records the returned model's
largest singular value, its frequency, enforcement path and outcome. Requested
enforcement is not substituted for the reported result.

Universal-model resistors are synthesis elements and are noiseless by default.
**Include passive thermal noise** requests snp2le's passive-network noise generator
rather than charging ordinary resistor noise against fit artifacts. This requires
strict passivity in the setupEM interface. If snp2le cannot generate the requested
noise, the run fails with diagnostics and no netlists are exported.

**Pin to supplied DC point** defaults on. With a finite source `S(0)`, snp2le can
add a low-pass correction toward the corresponding DC admittance. Its default
corner is 160 Hz; the optional island-leak conductance defaults to zero. The engine
can make the target real/symmetric, clip it, or reject a correction after its
passivity, RF-band movement and DC-matrix checks. The report includes the actual
DC-pin outcome and modifications. A supplied point created by extrapolation is
still an extrapolated target, not a solved DC result.

Without a finite DC sample, pinning is inactive and the model's DC behavior is
extrapolated from AC data. Use Postprocessing → DC extension to make an explicitly
documented derivative if that is appropriate, then select that derivative here.
This fitting tab does not invent a source DC point. Its fitted Touchstone export
contains positive-frequency fit samples; DC behavior is represented by the circuit
model and reported separately.

The operating-point health check evaluates the model's internal DC matrix with
reference-impedance port terminations. It does not certify convergence in every
external circuit, harmonic-balance analysis or transient simulation. The backend's
fit passivity result and the checked DC correction are separate diagnostics.

## Files and reproducibility

Each run contains:

- `input.sNp`: byte-identical source snapshot, including any original DC row.
- `run.json`: original path/hash/comments, specification, engine Python, adapter
  identity, status and output hashes.
- `fit_report.json`: snp2le/scikit-rf versions, core module hashes, effective engine
  state, actual order, fit band, reference impedance, per-trace errors, passivity,
  DC and noise diagnostics, and engine messages.
- `<subcircuit>.spice`, `.inc` and/or `.cir`: Ngspice, VACASK and Xyce netlists.
  Names are sanitized with snp2le's naming rules. Headers retain source provenance
  and original Touchstone metadata. VACASK uses Spectre syntax; this integration
  does not claim separate validation with Cadence Spectre.
- `normalized_data.sNp` and `fitted.sNp`: source/model on the native fit grid and
  a common real reference. snp2le preserves an already-common real reference or
  normalizes other references to 50 ohm and reports it.
- `fit_arrays.npz`: `frequency_hz`, `data_s`, `model_s` for subsequent analysis.
- `console.log`: engine progress and diagnostics.

Files/folders and original sources are never automatically overwritten. Failed
or stopped runs remain for diagnosis; partial files are not a completed model.
Editing controls leaves the last run's diagnostics identifiable until a new fit
is performed. Settings persist in a separate native simcfg `broadband` section,
including linked-script sidecars, not in solver settings or generated EM scripts.
An untouched tab adds no configuration keys.

## Engine environment

snp2le is optional and needs Python 3.10+ and a recent scikit-rf. Use a dedicated
Python environment if other CAD tools pin an older scikit-rf. For example:

```bash
python -m venv /path/to/snp2le-env
/path/to/snp2le-env/bin/python -m pip install /usr/cadtools/snp2le
```

Select that environment's Python under **Engine Python**. For an environment
without conflicting requirements, `pip install 'setupEM[broadband]'` is also
available. Do not install that extra into an environment whose other packages
require an incompatible scikit-rf.

The local setup uses `.tools/snp2le-env/bin/python`, ignored by Git. It shares
base libraries with emshrimulator but has its own snp2le and scikit-rf packages
for backend use only. The main environment keeps scikit-rf 1.9.0 for gerber2ems;
the backend uses scikit-rf 2.2.0. Do not use the backend environment to run gerber2ems.
The engine path is discovered from `EMS_BROADBAND_PYTHON`, a local `.tools/snp2le-env`,
or the current Python, in that order. A custom path can be saved in the simcfg.

The worker calls snp2le's Qt-free `engine.convert` in a separate process, limiting
BLAS threads to one. Stopping the fit cannot interrupt the GUI's numerical state.
The existing **Create Model → Model Fit** shortcut also uses Engine Python when
launching snp2le's standalone GUI, keeping its schematic and other tools available.
Circuit-simulator execution and geometry optimization are outside this tab.
