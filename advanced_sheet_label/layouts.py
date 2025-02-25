"""
ELEKTRON (c) 2024 - now
Written by melektron
www.elektron.work
18.07.24 22:42

List of sheet label paper layouts
"""

import dataclasses


@dataclasses.dataclass
class PaperSize:
    display_name: str   # paper size display name (e.g. "A4")
    width: float        # mm
    height: float       # mm


@dataclasses.dataclass
class SheetLayout:
    display_name: str
    page_size: PaperSize
    label_width: float      # mm
    label_height: float     # mm
    columns: int
    rows: int
    column_spacing: float   # mm
    row_spacing: float      # mm
    corner_radius: float                # mm, 0 means sharp corners
    spacing_top: float | None = None    # None means automatic centering
    spacing_left: float | None = None   # None means automatic centering

    @property
    def cells(self) -> int:
        return self.rows * self.columns

    @property
    def spacing_top_computed(self) -> float:
        if self.spacing_top is not None:
            return self.spacing_top
        else:
            return (
                self.page_size.height - (self.label_height * self.rows + self.row_spacing * (self.rows - 1))
            ) / 2
    
    def row_position_top(self, row: int) -> float:
        """
        returns the distance from the top of the page
        to the top of the specified row (starting with 0)
        """
        return self.spacing_top_computed + row * (self.label_height + self.row_spacing)
        
    @property
    def spacing_left_computed(self) -> float:
        if self.spacing_left is not None:
            return self.spacing_left
        else:
            return (
                self.page_size.width - (self.label_width * self.columns + self.column_spacing * (self.columns - 1))
            ) / 2

    def column_position_left(self, column: int) -> float:
        """
        returns the distance from the left edge of the page
        to the left edge of the specified column (starting with 0)
        """
        return self.spacing_left_computed + column * (self.label_width + self.column_spacing)

    def __str__(self) -> str:
        return f"{self.display_name} ({self.page_size.display_name}, {self.label_width}mm x {self.label_height}mm, {self.columns} columns x {self.rows} rows, {'round corners' if self.corner_radius != 0 else 'sharp corners'})"

PAPER_SIZES = {
    "A4": PaperSize("A4", 210, 297),
    "Letter": PaperSize("Letter", 215.9, 279.4)
}

LAYOUTS = {
    "4780": SheetLayout(
        display_name="4780",
        page_size=PAPER_SIZES["A4"],
        label_width=48.5,
        label_height=25.4,
        columns=4,
        rows=10,
        column_spacing=0,
        row_spacing=0,
        corner_radius=0
    ),
    "4737": SheetLayout(
        display_name="4737",
        page_size=PAPER_SIZES["A4"],
        label_width=63.5,
        label_height=29.6,
        columns=3,
        rows=9,
        column_spacing=2.54,
        row_spacing=0,
        corner_radius=3
    ),
    "4201": SheetLayout(
        display_name="4201",
        page_size=PAPER_SIZES["A4"],
        label_width=45.7,
        label_height=16.9,
        columns=4,
        rows=16,
        column_spacing=2.6,
        row_spacing=0,
        corner_radius=2
    ),
    "7120-25": SheetLayout(
        display_name="7120-25",
        page_size=PAPER_SIZES["A4"],
        label_width=35,
        label_height=35,
        columns=5,
        rows=7,
        column_spacing=5,
        row_spacing=5,
        corner_radius=0
    ),
    "7160-10": SheetLayout(
        display_name="7160-10",
        page_size=PAPER_SIZES["A4"],
        label_width=63.5,
        label_height=38.1,
        columns=3,
        rows=7,
        column_spacing=2.54,
        row_spacing=0,
        corner_radius=2.54
    ),
    "4360": SheetLayout(
        display_name="4360",
        page_size=PAPER_SIZES["A4"],
        label_width=70.0,
        label_height=36.0,
        columns=3,
        rows=8,
        column_spacing=0,
        row_spacing=0,
        corner_radius=0
    ),
    "Avery 5195": SheetLayout(
        display_name="Avery 5195",
        page_size=PAPER_SIZES["Letter"],
        label_width=44.45,
        label_height=16.92,
        columns=4,
        rows=15,
        column_spacing=7.49,
        row_spacing=0,
        corner_radius=1.25,
        spacing_top=12.83
    )
}

LAYOUT_SELECT_OPTIONS = [
    ("auto_round", "Auto (round) - Automatically detect correct layout for label template according to metadata or size (prefer round-corner labels)"),
    ("auto_sharp", "Auto (sharp) - Automatically detect correct layout for label template according to metadata or size (prefer sharp-corner labels)")
] + [
    (
        code, 
        str(layout)
    ) 
    for code, layout in LAYOUTS.items()
]

