# Network parameter postprocessing

The Postprocessing tab analyzes existing Touchstone networks from openEMS,
Palace, Elmer or other tools. It has **Parameters**, **DC extension** and
**Lumped models**, **Broadband Model** and **Plot** sub-tabs. The first three share
a loaded source file; Broadband Model has its own N-port source and Plot maintains
its own comparison list. It does not run an EM
solver, change the source file or recalibrate a result.

## Workflow

1. Browse to an `.sNp` file, or use **Find current results** to list files from
   the current run. Calibration-standard subdirectories are excluded from that
   list. Raw and calibrated files remain distinct; choose deliberately, then Load.
2. Select ports A and B, including pairs from networks with more than two ports.
3. Choose the termination of unused ports: **matched** to their own source-file
   reference impedances, or **open circuit** (zero current). Neither option means
   grounding them. This choice is recorded in exports and can change the result.
4. Choose differential inductor or uniform transmission line. For a line, enter
   the physical length and its units; no geometry-based length is guessed.
5. Set a display/analysis frequency range. Maximum zero means the source-file end.
   Analyze opens a separate, resizable plot window showing native positive-frequency
   samples without smoothing or extrapolation. Maximize it or move it to another monitor.
6. Set Readout frequency, or click a plot, to inspect the **nearest native sample**.
   The displayed actual frequency makes the sampling choice explicit. The plot
   window has a synchronized frequency control and compact sample readout too.
7. Export a CSV plus a JSON sidecar, or save a PNG/SVG through the plot toolbar.
   Existing parameter exports and source Touchstone files are protected from
   overwrite. JSON includes source path/SHA-256, original Touchstone comments,
   extraction specification, analysis implementation/version, warnings and summary.

Changing controls invalidates export until Analyze is run again. A plot retained
from the previous analysis is labeled as such. Analysis settings are stored in a
separate `postprocessing` section of native simcfg files, including linked-script
sidecars; they are not inserted into solver settings or generated solver scripts.

Setup, summaries and extracted values stay in the postprocessing page. Figures
open in independent **Extracted parameters** and **Network comparison** windows
with their own zoom/pan/export toolbar. Closing a plot window hides it without
discarding its figure; **Show plots…** reopens it. Running a new analysis updates
the same window. Closing setupEM also closes these plot windows.

## Differential inductor

Drive +I at A and -I at B. The differential impedance is

    Zdiff = ZAA - ZAB - ZBA + ZBB
    R = real(Zdiff)
    L = imag(Zdiff) / (2*pi*f)
    Q = imag(Zdiff) / real(Zdiff)

The implementation solves the prescribed-current boundary conditions directly.
A floating common-mode voltage is acceptable only if the differential voltage
is unique and the current equations are consistent. No artificial shunt or
numerical damping is added. This also permits ideal floating series inductors
whose individual grounded Z parameters are undefined.

Peak Q is the maximum native sample in the selected inductive band, before the
first noninductive sample. The reported reactance zero interpolates adjacent
positive-to-nonpositive reactance samples; it is not a fitted resonance. Negative
L/Q remains visible in capacitive bands. These are terminal/fixture-dependent
parameters, not a proof that all observed losses belong to the inductor alone.

## Uniform transmission line

The chosen pair is treated as two **single-ended line ends** sharing the source
network's reference. A differential four-port line requires a mixed-mode
reduction first; selecting an arbitrary pair does not perform that conversion.

From the selected two-port ABCD matrix:

    Zc = sqrt(B/C), choosing the branch with nonnegative real part
    exp(gamma*l) = (A+D)/2 + (B/Zc + C*Zc)/2
    gamma = alpha + j*beta
    R + j*w*L = gamma*Zc
    G + j*w*C = gamma/Zc
    epsilon_eff = (c*beta/w)^2

Physical length is required. CSV columns use SI units; plots/readouts use labeled
engineering units such as nH/mm, pF/mm and dB/mm. Characteristic impedance is
complex, and R/L/G/C may vary with frequency.

Phase is unwrapped over the full positive source band **before** applying the
selected display range. The default branch offset is zero and assumes a known
low-frequency principal branch. An integer offset adds complete 2*pi turns at
the first positive source sample. Sparse frequency spacing or a source band
starting after unknown phase wraps cannot be resolved from one length alone.
Singular gaps break phase continuity and require separate branch review.

Reciprocity, symmetry and uniform-line reconstruction residuals are reported.
A reconstruction residual above 2% flags the result as an effective approximation,
not a validated uniform-line model. The 2% threshold is a diagnostic policy, not
an accuracy guarantee. Launches, tapers and discontinuities must already have
been de-embedded or explicitly accepted as part of the effective model.

## Limits and extension API

Only finite, real, positive source reference impedances are supported currently.
DC is excluded. Singular/nonfinite samples remain undefined, rather than being
silently regularized. Unused open-circuit modes are accepted only when the chosen
response remains unique and consistent.

## DC extension

A sweep requested from 0 Hz does not imply a solved or calibrated DC point. For
example, boxwall calibration deliberately excludes zero from its frequency array.
The DC extension sub-tab works on **all ports of the loaded source**, independent
of the selected pair, displayed band and line length.

Choose either:

- **scikit-rf**: `Network.extrapolate_to_dc()` estimates DC from the two lowest
  AC samples using linear magnitude/unwrapped-phase extrapolation and makes the
  DC matrix real. setupEM takes only this DC row from the returned network and
  prepends it to the original data. scikit-rf normally resamples the entire sweep;
  setupEM deliberately preserves the native AC rows instead.
- **Real S fit**: least-squares linear extrapolation of real S versus frequency
  over the lowest N samples. This is a comparison/estimation choice, not a
  replacement for physical DC information.

The preview reports the real DC S matrix, estimation band, difference from a
two-point Cartesian estimate, estimated differential DC resistance for two ports,
and largest DC singular value. A value above one
flags nonpassivity for the supported real references. No passivity correction is
applied. Existing DC points are never replaced; frequency-dependent/complex
reference impedances must first be renormalized outside this tool.

**Export separate .sNp + DC report** writes a derivative (suggested suffix `_dc`)
and `.dc.json` sidecar. Existing files cannot be overwritten. Original comments,
source hash, method, warnings and an explicit **EXTRAPOLATED DC, not solved** label
are retained. Common reference impedances use ordinary Touchstone; unequal real
port references use Touchstone 2.0 `[Reference]` entries. Check that your circuit
simulator supports the chosen format.

This estimated point is not a conduction/magnetostatic solve, a validated DC
resistance, a broadband passivity/causality certificate or a transient validation.
Known DC connectivity and resistance, or a separately solved DC network, are
better constraints. Especially when the first simulated point is high in
frequency, compare estimates and obtain lower-frequency data when needed.

Reference: [scikit-rf DC extrapolation API](https://scikit-rf.readthedocs.io/en/latest/api/generated/skrf.network.Network.extrapolate_to_dc.html).

## Plot: compare multiple files

Use **Add files** to select several Touchstone results, or **Add loaded result**
to copy the source and port selection from Parameters. Each editable row has:

- A Use checkbox to include/exclude the dataset without deleting it.
- File path and optional short legend name. A blank name uses the filename;
  duplicate names are disambiguated with `(2)`, `(3)`, etc.
- Port A/B and matched/open termination of unused ports, independently per file.
- Line + markers, plain line, or points-only styling. Marker shapes and colors
  help reveal overlapping curves. Points-only curves omit peak/resonance estimates.

**Inductor L / R / Q** uses the same differential extraction as Parameters and
the earlier comparison script. Optional low-band panels (default through 8 GHz)
appear alongside the full selected band. Negative L/Q remains visible. The
minimum and maximum controls define the analysis band; maximum zero uses each
file's own end. Files keep their own frequency grids; there is no smoothing,
resampling or automatic truncation to the shortest file's band.
**Plot comparison** opens the overlay in the separate Network comparison window,
leaving the file list, options and readout table available in the main page.

**Raw S-parameters** overlays Saa, Sba, Sab and Sbb in magnitude dB/unwrapped
phase, or real/imaginary views. These names refer to each row's A/B terminals;
for example Sba is response at B for excitation at A. For multiport files the
unused-port condition is applied explicitly. DC is retained when the minimum
is zero. Zero S magnitude has `-inf` dB and undefined phase; no artificial floor
is inserted. Phase unwrap uses the full native grid before band selection and
does not bridge undefined samples.

Reference impedances are retained by default. If they differ, raw comparisons
display a warning. **Common reference** explicitly renormalizes the selected
ports to the given real impedance, preserving the original matched loads at
unused terminals. Original references and the chosen normalization are recorded.

The readout frequency, or clicking any plot, selects the nearest native sample
**independently for each file**; the table shows the actual sample frequencies.
Inductor readout includes L/R/Q and native peak-Q estimates in the selected band.
Raw readout shows complex S values. Editing comparison inputs invalidates export
and labels the retained plot as previous until **Plot comparison** runs again.

**Export plots + native CSVs + provenance** creates a new comparison folder with
PNG/SVG plots, one native CSV per enabled dataset, and `comparison.json` containing
legend names, selections, styles, source paths/hashes/comments, reference settings,
diagnostics and summaries. Existing folders and source files are preserved.
The Matplotlib toolbar also supports individual plot export and zoom/pan.
Comparison rows and options persist in the native simcfg's separate postprocessing
section; the list is independent of the single loaded source at the top.

## Lumped models

Select a local checkout of [Volker Muehlhaus's lumpedmodel](https://github.com/VolkerMuehlhaus/lumpedmodel)
(GPL-3.0-or-later). The GUI discovers `/usr/cadtools/lumpedmodel` or
`/local/cadtools/lumpedmodel` when available, or use Browse on another machine.
The scripts remain a separate installation; setupEM neither modifies nor vendors
them. They run with setupEM's current Python environment and dependencies.

Available adapters:

| Tool | Use | Outputs supplied by the tool |
|---|---|---|
| `inductor_fit` | Wideband two-port inductor; optional basic topology and Spectre format | SPICE/Spectre subcircuit, fitted S2P, report and comparison plots |
| `pi_from_s2p` | Inductor pi extraction at a target frequency, plus series-branch fitting | Component report and comparison plots |
| `mim_from_s2p` | MIM capacitor extraction at a target frequency | Component report and plot |
| `rlgc_from_s2p` | Single-ended line extraction at a target frequency and physical length | RLGC report |

Choose ports, unused-port terminations, band and line length in **Parameters**.
Unlike the DC sub-tab, these adapters operate on the selected two-port. Open
unused ports are reduced with their zero-current boundary condition; matched
ports are terminated in their source references. The reduced network is then
renormalized to 50 ohm, as these scripts expect a common scalar reference. Four
or more valid positive samples are required. Undefined samples fail preparation.
DC is omitted from fitting, including a synthetic DC row in a loaded file.

Run chooses a parent directory and creates a unique child directory. The GUI
stays responsive, streams the process log and offers Stop fit. The tools'
`plt.show()` calls are captured as PNG files, accessible through **View selected
output** alongside netlists, reports and model S2P files. CPU library threads are
limited to one in this child process to avoid unintended oversubscription.
Closing the application stops an active fit.

Each run contains `selected_ports.s2p`, `console.log`, and `run.json` with the
original source comments/hash, selected ports and terminations, actual band,
normalization, external script path/hash, Python executable, command arguments,
exit status and output hashes. A failed/stopped run stays available for review;
its partial files are not a completed model. Earlier fits and source files are
never overwritten.

The inspected tools do **not** call scikit-rf's DC extrapolation function. They
estimate circuit elements from AC data. The resulting circuit's DC behavior is
therefore model-dependent and must be reviewed, particularly if low frequencies
were excluded. A target-frequency extraction is not a wideband validation.
These adapters currently use two ports; the standalone inductor tool's
center-tapped three-port mode is not exposed here. General vector fitting and
geometry optimization are left for the separate future workflow.

`setupEM.network_parameters` is independent of Qt/matplotlib and exposes:

- `ExtractionSpec`: immutable selection, termination, line length, phase and band.
- `load_touchstone(path)`: a network plus source identity captured on loading.
- `extract_parameters(network, spec, source)`: frequency arrays, SI-valued columns,
  summary, warnings and structured provenance in `ParameterResult`.
- `export_parameters(result, csv_path)`: CSV and JSON without overwriting sources.

This numeric layer can supply model-fitting objectives and geometry-optimization
metrics later. Those workflows are not implemented by this tab yet. The existing
optional snp2le Model Fit tool remains separate.
