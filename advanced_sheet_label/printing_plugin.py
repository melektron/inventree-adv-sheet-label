"""
Label printing plugin which supports printing multiple labels on a single page 
arranged according to standard label sheets.
"""

import logging
import math

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _

from rest_framework.request import Request
import weasyprint
from rest_framework import serializers
from plugin import InvenTreePlugin
from plugin.mixins import LabelPrintingMixin, SettingsMixin

version_pre_0_16_x: bool = ...
try:
    from label.models import LabelOutput, LabelTemplate     # for current stable version (0.15.x)
    version_pre_0_16_x = True
except ImportError:
    from report.models import LabelOutput, LabelTemplate    # for newer versions (0.16.x)
    version_pre_0_16_x = False

from .layouts import SheetLayout, LAYOUTS, LAYOUT_SELECT_OPTIONS


_log = logging.getLogger('inventree-adv-sheet-label')
#_log.setLevel(logging.DEBUG)
_plugin_instance: "AdvancedLabelSheetPlugin" = ...


def get_default_layout() -> str:
    """
    Fetches the default layout setting from the database to show in form.
    """
    if _plugin_instance is not ...: 
        return _plugin_instance.get_setting("DEFAULT_LAYOUT")
    else:
        return LAYOUT_SELECT_OPTIONS[0][0]    # use the first one if there is no other option (is)

def get_default_skip() -> int:
    """
    Fetches the default labels skip count from the database which was stored
    there the last time a printing job finished to indicate the next available label
    positions.
    """
    if _plugin_instance is not ...: 
        return _plugin_instance.label_skip_counter
    return 0


class AdvancedLabelPrintingOptionsSerializer(serializers.Serializer):
    """Custom printing options for the advanced label sheet plugin."""

    sheet_layout = serializers.ChoiceField(
        label='Sheet layout',
        help_text='Page size and label arrangement',
        choices=LAYOUT_SELECT_OPTIONS,
        default=get_default_layout,
    )

    count = serializers.IntegerField(
        label='Number of labels',
        help_text='Number of labels to print for each kind',
        min_value=0,
        default=1,
    )

    skip = serializers.IntegerField(
        label='Skip label positions',
        help_text='Number of label positions to skip from the top left',
        min_value=0,
        default=get_default_skip,
    )

    ignore_size_mismatch = serializers.BooleanField(
        label='Ignore label size mismatch',
        help_text="Whether to ignore that the label size doesn't match the expedted label size of the selected layout",
        default=False
    )

    border = serializers.BooleanField(
        label='Debug: Print border',
        help_text='Whether to print a border around each label for testing',
        default=False,
    )

    fill_color = serializers.CharField(
        label="Debug: Label fill color",
        help_text="Background color to fill all the labels with. This helps make the shape and size clearer for testing.",
        default="unset"
    )



class AdvancedLabelSheetPlugin(LabelPrintingMixin, SettingsMixin, InvenTreePlugin):
    """Plugin for advanced label sheet printing.

    This plugin arrays multiple labels onto a single larger sheet,
    and returns the resulting PDF file.
    """

    NAME = 'AdvancedLabelSheet'
    TITLE = 'Advanced Label Sheet Printer'
    DESCRIPTION = 'Arrays multiple labels onto single, standard layout label sheets with additional useful features'
    VERSION = '1.2.1'
    AUTHOR = 'InvenTree contributors & melektron'

    BLOCKING_PRINT = True

    SETTINGS = {
        "DEFAULT_LAYOUT": {
            "name": "Default sheet layout",
            "description": "The default sheet layout selection when printing labels",
            "choices": LAYOUT_SELECT_OPTIONS,
            "default": LAYOUT_SELECT_OPTIONS[0][0],
            "required": True
        },
        "LABEL_SKIP_COUNTER": {
            "name": "Label skip counter",
            "description": "Global counter for auto-incrementing the default amount of labels to skip when printing. If page is full, this wraps back to zero accordingly.",
            "default": 0,
            "validator": [
                int,
                MinValueValidator(0)
            ],
            "hidden": True  # maybe shoudl actually show this for manual reset? but for now I'll not show it
        }
    }

    PrintingOptionsSerializer = AdvancedLabelPrintingOptionsSerializer

    #def __init__(self):
    #    _log.debug("Initializing Advanced Sheet Label Plugin")
    #    super().__init__()
    #    # save instance so serializers can access it.
    #    global _plugin_instance
    #    _plugin_instance = self
    
    @property
    def label_skip_counter(self) -> int:
        return self.get_setting("LABEL_SKIP_COUNTER")
    
    @label_skip_counter.setter
    def label_skip_counter(self, counter: int) -> None:
        self.set_setting("LABEL_SKIP_COUNTER", counter)

    def _find_closest_match(self, label: LabelTemplate, prefer_round: bool) -> tuple[SheetLayout, bool, bool]:
        """
        Finds the best matching layout to use for a specific label template.
        If the template has specified the correct layout using the "sheet_layout" key
        in the template metadata and that layout exists, it is used.
        Otherwise a layout with correct size is returned, regarding a round/sharp 
        corner preference if two exact matches of both are found.
        If no exact size is found, the closest contendor is returned as a last
        resort.

        Returns: 
            layout: best matching sheet label layout
            specified: whether the layout was specified in metadata or looked for via size
            exact: whether the result size matches exactly or not
        """
        # check for specified info in metadata:
        if isinstance(label.metadata, dict) and "sheet_layout" in label.metadata:
            layout_code = str(label.metadata["sheet_layout"])
            if layout_code in LAYOUTS:
                layout = LAYOUTS[layout_code]
                return (
                    layout,
                    True,
                    layout.label_height == label.height and layout.label_width == label.width
                )
        
        # find match according to size
        # define cost function: geometric average of size and width deviation. too small is always infinite cost
        cost_function = lambda dw, dh: float("inf") if dw < 0 or dh < 0 else math.sqrt(dw**2 + dh**2)
        # collect exact size matches
        exact_matches: list[SheetLayout] = []
        # collect the closest match if nothing exact is found
        closest_match: tuple[float, SheetLayout] = ...

        # go through all layouts to find best solution
        for _, layout in LAYOUTS.items():
            if (    # if we have exact matches, no need to check for closest contender
                (layout.label_height == label.height and layout.label_width == label.width)
                or len(exact_matches) > 0
            ):
                exact_matches.append(layout)
                continue

            # calculate the cost and save if it was better than the last one
            cost = cost_function(
                layout.label_width - label.width,
                layout.label_height - label.height,
            )
            _log.debug(f"{layout=}: costs {cost}")
            if closest_match is ... or cost < closest_match[0]:
                closest_match = (cost, layout)
        
        if len(exact_matches) > 0:  # exact matches have been found
            # find the prefered match
            for match in exact_matches:
                if prefer_round and match.corner_radius > 0:
                    return match, False, True
                elif not prefer_round and match.corner_radius == 0:
                    return match, False, True
            # otherwise just return the first one
            return exact_matches[0], False, True

        # no exact matches found
        return closest_match[1], False, False
    
    if version_pre_0_16_x:
        def print_labels(
            self, label: LabelTemplate, items: list, request: Request, **kwargs
        ):
            """
            Printing interface for InvenTree 0.15.x (current stable)
            """
            output_file = ContentFile(self._print_labels(label, items, request, **kwargs), 'labels.pdf')
            output = LabelOutput.objects.create(label=output_file, user=request.user)
            return JsonResponse({
                'file': output.label.url,
                'success': True,
                'message': f'{len(items)} labels generated',
            })
        
    else:
        def print_labels(
            self, label: LabelTemplate, output: LabelOutput, items: list, request, **kwargs
        ):
            """
            Printing interface for InvenTree 0.16.x (currently not released yet)
            """
            output.output = ContentFile(self._print_labels(label, items, request, **kwargs), 'labels.pdf')
            output.progress = 100
            output.complete = True
            output.save()
        
    def _print_labels(
        self, label: LabelTemplate, input_items: list, request, **kwargs
    ) -> bytes:
        """
        Handle printing of the provided labels.
        Note that we override the entire print_label**s** method for this plugin
        so we can arrange them all on pages.

        This function is an internal function which returns the rendered PDF document.
        The responding and uploading is handled by one of the two defined print_label()
        functions depending on whether we are running in InvenTree v0.15.x or v0.16.x because
        the API has changed since then
        """

        # extract the printing options from request
        printing_options = kwargs['printing_options']
        sheet_layout_code: str = printing_options.get("sheet_layout", get_default_layout())
        label_count: int = printing_options.get("count", 1)
        skip_count: int = printing_options.get("skip", 0)
        ignore_size_mismatch: bool = printing_options.get("ignore_size_mismatch", False)
        border: bool = printing_options.get("border", False)
        fill_color: str = printing_options.get("fill_color", "")

        # get sheet layout information
        sheet_layout: SheetLayout = ...

        if sheet_layout_code in ["auto_round", "auto_sharp"]:   # automatic detection
            sheet_layout, specified, is_exact = self._find_closest_match(label, sheet_layout_code == "auto_round")
            if not is_exact and not ignore_size_mismatch:
                if specified:
                    raise ValidationError(f"The layout specified in the template metadata (<i>{str(sheet_layout)}</i> ) does not have the correct label size. Select '<i>Ignore label size mismatch</i>' to use it anyway.")
                else:
                    raise ValidationError(f"The template ({label.width}mm x {label.height}mm) does not specify any valid sheet layout to use and no exact size match was found. <i>{str(sheet_layout)}</i> is the closest contender. Select '<i>Ignore label size mismatch</i>' to use it.")
        else:   # explicit layout selection
            try:
                sheet_layout = LAYOUTS[sheet_layout_code]
            except IndexError:
                raise ValidationError(f"Sheet layout '<i>{sheet_layout_code}</i>' does not exist.")

            if ((sheet_layout.label_height != label.height 
                or sheet_layout.label_width != label.width)
                and not ignore_size_mismatch):
                raise ValidationError(f"Label size ({label.width}mm x {label.height}mm) does not match the label size required for the selected layout (<i>{str(sheet_layout)}</i>). Select '<i>Ignore label size mismatch</i>' to continue anyway.")

        # generate the actual list of labels to print by prepending the
        # required number of skipped null labels and multiplying each lable by the
        # specified amount
        items = [None] * skip_count + [
            label
            for item in input_items
            for label in [item] * label_count
        ]

        # calculate all the used up label positions and store the new automatic skip
        # count for next time.
        self.label_skip_counter = len(items) % sheet_layout.cells   # only count skips on last page

        # generate all pages
        pages = []
        idx = 0
        while idx < len(items):
            if page := self.print_page(
                label, items[idx : idx + sheet_layout.cells], request, sheet_layout
            ):
                pages.append(page)

            idx += sheet_layout.cells

        if len(pages) == 0:
            raise ValidationError(_('No labels were generated'))

        # render to a single HTML document
        html_data = self.wrap_pages(pages, border, fill_color, sheet_layout)

        # render HTML to PDF
        html = weasyprint.HTML(string=html_data)
        return html.render().write_pdf()

    def print_page(self, label: LabelTemplate, items: list, request, sheet_layout: SheetLayout):
        """Generate a single page of labels.

        For a single page, generate a table grid of labels.
        Styling of the table is handled by the higher level label template

        Arguments:
            label: The LabelTemplate object to use for printing
            items: The list of database items to print (e.g. StockItem instances)
            request: The HTTP request object which triggered this print job
            sheet_layout: the layout information of a page
        """

        # Generate a table of labels
        html = """<table class='label-sheet-table'>"""

        for row in range(sheet_layout.rows):
            html += "<tr class='label-sheet-row'>"

            for col in range(sheet_layout.columns):
                # Cell index
                idx = row * sheet_layout.columns + col

                if idx >= len(items):
                    break

                html += f"<td class='label-sheet-cell label-sheet-row-{row} label-sheet-col-{col}'>"

                # If the label is empty (skipped), render an empty cell
                if items[idx] is None:
                    html += """<div class='label-sheet-cell-skip'></div>"""
                else:
                    try:
                        # Render the individual label template
                        # Note that we disable @page styling for this
                        if version_pre_0_16_x:
                            cell = label.render_as_string(
                                request, target_object=items[idx], insert_page_style=False
                            )
                        else:
                            cell = label.render_as_string(
                                items[idx], request, insert_page_style=False
                            )
                        html += cell
                    except Exception as exc:
                        _log.exception('Error rendering label: %s', str(exc))
                        html += """
                        <div class='label-sheet-cell-error'></div>
                        """
                
                # overlay for border
                html += "<div class='label-sheet-cell-overlay'></div>"

                html += '</td>'

            html += '</tr>'

        html += '</table>'

        return html

    def wrap_pages(self, pages, enable_border: bool, fill_color: str, sheet_layout: SheetLayout):
        """Wrap the generated pages into a single document."""

        inner = ''.join(pages)

        # Generate styles for individual cells (on each page)
        cell_styles = []

        for row in range(sheet_layout.rows):
            cell_styles.append(
                f"""
            .label-sheet-row-{row} {{
                top: {sheet_layout.row_position_top(row)}mm;
            }}
            """
            )

        for col in range(sheet_layout.columns):
            cell_styles.append(
                f"""
            .label-sheet-col-{col} {{
                left: {sheet_layout.column_position_left(col)}mm;
            }}
            """
            )

        cell_styles = '\n'.join(cell_styles)

        return f"""
        <head>
            <style>
                @page {{
                    size: {sheet_layout.page_size.width}mm {sheet_layout.page_size.height}mm;
                    margin: 0mm;
                    padding: 0mm;
                }}

                .label-sheet-table {{
                    page-break-after: always;
                    table-layout: fixed;
                    width: {sheet_layout.page_size.width}mm;
                    border-spacing: 0mm 0mm;
                }}

                .label-sheet-cell-error {{
                    background-color: #F00;
                }}

                .label-sheet-cell {{
                    width: {sheet_layout.label_width}mm;
                    height: {sheet_layout.label_height}mm;
                    padding: 0mm;
                    position: absolute;
                    {'background-color: ' + fill_color + ';' if fill_color not in ["", "unset"] else ''};
                    border-radius: {sheet_layout.corner_radius}mm;
                }}

                .label-sheet-cell-overlay {{
                    border: {'0.25mm solid #000' if enable_border else '0mm'};
                    border-radius: {sheet_layout.corner_radius}mm;
                    box-sizing: border-box;
                    width: {sheet_layout.label_width}mm;
                    height: {sheet_layout.label_height}mm;
                    padding: 0mm;
                    position: absolute;
                    top: 0px;
                    left: 0px;
                }}

                {cell_styles}

                body {{
                    margin: 0mm !important;
                }}
            </style>
        </head>
        <body>
            {inner}
        </body>
        </html>
        """
