# PerfBoardMaker ⚡

A desktop 2D orthogonal electronic CAD application for designing and prototyping perfboard circuits.

## Key Features

- **Viewport Toolbar & Modes**:
  - Located directly above the perfboard canvas spanning the full viewport width.
  - **Select Mode (`1`)**:
    - Select and drag components or jumper cables; rotate parts with `R`.
    - **Draggable Jumper Endpoints**: Grab a jumper's start or end handle and drag it to any hole.
    - **Solder Net Highlighting**: Hovering over any solder bridge or pad in the **Back View** highlights the entire conductive solder net with a glowing gold halo to inspect connections.
  - **Solder Mode (`2`)**:
    - Draw realistic molten solder bridges on the back side of the board.
    - Traces do not merge unless explicitly drawn from/to the same hole.
    - **Solder Deletion (`Ctrl + Drag/Click`)**: Hold **`LCtrl`** while in solder mode to erase soldered holes and bridges. Disconnected parts are cleanly split.
    - Hold **`Shift`** while drawing to lock to a horizontal or vertical straight line.
    - When solder mode is active in the front view, translucent solder ghosts are shown; hidden when not in solder mode.
  - **Jumper Mode (`3`)**:
    - **Straight Jumpers**: All jumpers are rendered as clean, straight insulated wires.
    - **Bend Points (`Shift + Click`)**: Hold **`Shift`** and click on any jumper wire body to insert a bend point (multiple bends supported!).
    - **Draggable Bends**: Drag bend handles to route wires around components snapping cleanly to hole positions without making electrical connections to intermediate holes.
    - Hold **`Shift`** while drawing to lock to horizontal or vertical straight wires.
    - Clickable wire color palette in both the Viewport Toolbar and the Inspector panel.

- **Procedural Perfboard Visual**:
  - Realistic FR4 / Phenolic Bakelite board substrate with metallic annular donut pads and drilled through-holes.
  - Coordinate grid rulers (Columns A-Z, AA-AH... and Rows 1-N).
  - Substrate themes: *Green FR4*, *Phenolic Brown (Bakelite)*, *Blue FR4*, and *Matte Black FR4*.
  - Configurable board sizes (Standard 34x24, Small 24x18, Compact 20x14, Large 48x32, Eurocard 60x40, or Custom).

- **Top & Bottom 2D Orthogonal Views**:
  - **Top View (Component Side)**: Displays component bodies, silkscreen markings, IC packages, and pins entering the holes.
  - **Bottom View (Solder Side)**: Physically mirrors the board horizontally ($x' = \text{width} - x$) as when turning over a real board. Renders tinned solder joints with pin leads, solder bridges, conductive net glow on hover, and translucent ghosted outlines of the top components.
  - Seamless toggle with hotkey **`F`** or the toolbar toggle button.

- **Built-in Key Components**:
  1. **Arduino Nano**: Full 30-pin DIP layout ($0.6''$ span, 15 pins per row at $0.1''$ pitch) with USB overhang, ATmega328P chip, reset button, crystal, and pinout labels (`D13` through `VIN`).
  2. **Push Button**: $6\times 6\,\text{mm}$ tactile momentary switch with 4 corner terminals ($5.08\times 5.08\,\text{mm}$ / 2×2 hole grid), corner crimps, and customizable cap color.
  3. **Electrolytic Capacitors (3+ Diameter Sizes)**:
     - Ø 5mm (1-hole lead pitch, $2.54\,\text{mm}$)
     - Ø 8mm (2-hole lead pitch, $5.08\,\text{mm}$)
     - Ø 10mm (2-hole lead pitch, $5.08\,\text{mm}$)
     - Ø 12.5mm (2-hole lead pitch, $5.08\,\text{mm}$)
  4. **TO-220 Package IC (Renameable)**: 3-pin inline layout with molded epoxy body, metal heat sink tab with mounting hole, and live editable label (e.g., `LM7805`, `IRFZ44N`, `TIP120`).
  5. **TO-92 Package IC (Renameable)**: 3-pin inline layout with curved D-shape package and live editable label (e.g., `2N2222`, `DS18B20`, `LM35`).
  6. **nRF24L01 Module**: $2\times 4$ pin header labeled `GND`, `VCC`, `CE`, `CSN`, `SCK`, `MOSI`, `MISO`, `IRQ`, with golden serpentine PCB antenna trace.
  7. **nRF24L01+PA+LNA Module**: $2\times 4$ pin header, silver metal RF shielding can, gold SMA connector, and $2.4\,\text{GHz}$ rubber duck whip antenna.

- **Keyboard Shortcuts**:
  - **`1`**: Select Mode
  - **`2`**: Solder Mode
  - **`3`**: Jumper Mode
  - **`LCtrl` + Click/Drag (in Solder Mode)**: Erase/delete solder bridges
  - **`Shift` + Click on wire (in Jumper Mode)**: Insert a bend point
  - **`Shift` while drawing or moving**: Lock to horizontal / vertical
  - **`R` / `Shift+R`**: Rotate component 90° CW / CCW
  - **`F`**: Flip Board (Top / Bottom)
  - **`Delete` / `Backspace`**: Delete selected component or jumper
  - **`Space + Drag` or `Middle/Right Drag`**: Pan canvas
  - **`Mouse Wheel`**: Zoom in / out
  - **`Ctrl+0`**: Fit board in view
  - **`Ctrl+E`**: Export image

## Running the App

```bash
python run.py
```
Or double-click `start.bat`.
