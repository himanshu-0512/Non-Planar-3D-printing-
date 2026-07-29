# Non-planar FDM on standard three-axis printers via a Siemens NX post-processing workflow

Post-processor and supporting scripts for generating non-planar FDM G-code for a
standard three-axis printer (Prusa MK4) from a subtractive **Multi-Axis Streamline**
operation in Siemens NX — without bespoke slicing software, custom slicing
algorithms, or multi-axis printer hardware.

This repository accompanies the paper:

> **Non-planar FDM on standard three-axis printers via a Siemens NX post-processing workflow**
> Amal Devassy, Atharva Balkrishna Tarde, Himanshu Sharma, Muhammed Saad Abdul Sathar
> Institute of Mechanical Engineering (IMW), Clausthal University of Technology, Germany.

## What this is

Conventional FDM deposits material in planar horizontal layers, which produces
staircasing on curved and inclined surfaces. This workflow treats the nozzle as a
virtual multi-axis tool: a Multi-Axis Streamline operation in Siemens NX produces a
surface-conforming trajectory, and a custom Post Builder post-processor converts it
into three-axis G-code.

The key idea is that the CAM tool-axis vector — which a conventional three-axis
post-processor would discard — is repurposed as a flow-compensation signal. The
per-block extrusion is scaled by the cosine of the local surface inclination (the K
component of the tool-axis vector), so a fixed vertical nozzle deposits the correct
amount of material along a curved surface. The post-processor emits no rotary-axis
registers.

The specimen was printed on a Prusa MK4: the non-planar surface was produced without
visible staircasing and matched the CAD nominal to within approximately 0.3–0.5 mm by
caliper measurement.

## Repository structure

```
.
├── README.md
├── LICENSE
├── CITATION.cff
├── post-processor/     Siemens NX Post Builder definition (.pui .tcl .def .cdl)
├── scripts/            Python conversion and verification tools
├── cad/                Validation specimen (STEP)
├── gcode/              Generated non-planar program, planar baseline, merged support
└── media/              Photographs of the printed specimen
```

## Requirements

- Siemens NX **[FILL: version]** with Post Builder **[FILL: version]**
- Python 3.8 or newer, with numpy (`pip install numpy`) for `merge_support.py`

The NX version matters: the post-processor definition is version-dependent and may not
load in a different release.

## Workflow

1. Open the CAD model in `cad/` in Siemens NX (Manufacturing application).
2. Create a **Multi-Axis Streamline** operation on the non-planar drive surface, with
   **Tool Axis = Normal to Drive Surface**.
3. Post-process the operation using the definition in `post-processor/`.
4. Convert the NX listing into a printable G-code file:
   ```
   python scripts/nx_listing_to_gcode.py listing.txt part.gcode
   ```
5. Verify the output before printing:
   ```
   python scripts/verify_extrusion.py part.gcode
   ```

## Process parameters

| Parameter | Symbol | Value | Unit |
|---|---|---|---|
| Nozzle orifice diameter | — | 0.40 | mm |
| Filament diameter | d | 1.75 | mm |
| Material | — | PLA | — |
| Nozzle temperature | — | 215 | °C |
| Bed temperature | — | 60 | °C |
| Layer offset (build direction) | h | 0.20 | mm |
| Bead width / stepover | w | 0.42 | mm |
| Flow modifier | α | 1.0 | — |
| Feed rate | — | 25 mm/s (1500 mm/min) | — |
| Planar base layers | — | 5 | — |

## Scripts

- **`nx_listing_to_gcode.py`** — converts the NX post listing into a valid G-code file.
  Removes the NX banner, tape marks, sequence numbers and `M02`; expands modal motion
  words to an explicit motion command on every line (required because Marlin and slicer
  parsers do not implement motion modality); normalises `G00`/`G01`; validates that the
  part fits the build volume.
- **`verify_extrusion.py`** — reports whether the extrusion-per-length tracks the local
  surface inclination (confirming the cosine compensation is active), the implied
  inclination range, travel/retraction balance, and total commanded filament.
- **`merge_support.py`** — concatenates a slicer-generated support structure with the
  non-planar program and checks for shell/support interference. See the scope note below.

Each script prints usage when run without arguments.

## Scope and limitations

The workflow generates a surface-conforming trajectory on a single non-planar drive
surface. It does not construct a sliced volumetric representation, and therefore has no
native infill or support generation — this is a direct consequence of generating a
surface rather than a solid. Where support structures are required, they are generated
by an external slicer (PrusaSlicer) and concatenated with the CAM-generated program;
the workflow is two-stage in that case. The approach was validated on a single hybrid
specimen with surface inclination up to approximately 34.4°. Quantitative surface
roughness (Ra, Rz) has not been measured.

## License

[FILL: MIT or CC-BY-4.0 — add the matching LICENSE file]

## Citation

If you use this work, please cite the paper above. A DOI for this repository will be
minted via Zenodo on release: **[FILL: DOI after first release]**.
```
