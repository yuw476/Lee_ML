    #Copyright 2014-2017 Juergen Probst, Carlo Barth
    #This program is free software; you can redistribute it and/or modify
    #it under the terms of the GNU General Public License as published by
    #the Free Software Foundation; either version 3 of the License, or
    #(at your option) any later version.

    #This program is distributed in the hope that it will be useful,
    #but WITHOUT ANY WARRANTY; without even the implied warranty of
    #MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    #GNU General Public License for more details.

    #You should have received a copy of the GNU General Public License
    #along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import division, print_function

import matplotlib as mpl
from matplotlib import pyplot as plt
if mpl.__version__ >= '1.4':
    from matplotlib.axes._base import _process_plot_format
else:
    from matplotlib.axes import _process_plot_format
from matplotlib.offsetbox import OffsetImage, AnchoredOffsetbox
import numpy as np
from itertools import cycle
from utility import get_intersection_knum, get_intersection
from axis_formatter import CustomAxisFormatter
import log
import defaults


class BandPlotter:
    def __init__(
            self, figure_size=defaults.fig_size,
            numrows=1, figure_name='bands', onclick=defaults.default_onclick):
        """ Prepare a new figure for plotting photonic bands.

        *figure_size* is the figure size in inches (x,y-tuple);
        *numrows* is the number of subplot rows in the figure.
        Provide a unique *figure_name* to create a new figure, or reuse the
        same *figure_name* for multiple plots to reuse figures.

        If *onclick* is a callable function with two positional arguments, and
        plot_bands is later called with a picker supplied, the function is
        called if the user clicks on a vertex in the plot. The two positional
        arguments supplied to the function are:
        1. the <matplotlib.backend_bases.PickEvent> object
        (with interesting fields:
        artist - the Line2D object which is the actual graph in the diagram
        containing the xy-data;
        ind - a list of the data indices of the Line2D data clicked on;
        mouseevent - among others with mouseevent.inaxes: the Axes objects
        receiving the click event)
        and 2. this Bandplotter instance, so the function can use the data and
        manipulate / add to the plot.
        By default, the function defaults.default_onclick is called, which
        just prints the vertex' data to stdout.

        """
        self._fig = plt.figure(figure_name, figsize=figure_size)
        self._fig.clf()
        self._fig.canvas.mpl_connect('pick_event', self._onpick)
        if callable(onclick):
            self._onclick = onclick
        else:
            self._onclick = None
        self._numplots = 0
        self._numrows = max(numrows, 1)
        self._axes = []
        # The last scatter plot that was added to overlay parity data on a
        # band diagram. Needed for when a color bar is added:
        self._last_parity_scatter = None

        self._x_data = None
        self._last_data = None
        self._last_kdata = None
        self._x_axis_corrected = False
        self.next_plot()

    def _onpick(self, event):
        """This is called if the bands are plotted with a picker supplied and
        the user clicks on a point in the plot. It then calls the onclick
        method supplied to Bandplotter on creation.

        """
        if self._onclick is not None:
            self._onclick(event, self)

    def next_plot(self):
        """Create a new subplot.

        Following calls to plot_bands and the add-methods will plot to this
        new subplot.

        """
        self._numplots += 1
        # add subplot somewhere where no other is yet. Final position
        # will be set in _distribute_subplots
        self._ax = self._fig.add_subplot(1, self._numplots, self._numplots)
        self._ax.set_ylabel(defaults.default_y_axis_label, size='x-large')
        self._ax.grid(True)
        self._axes.append(self._ax)

        self._x_data = None
        self._last_data = None
        self._last_kdata = None
        self._x_axis_corrected = False
        self._miny = float('inf')
        self._maxy = -float('inf')
        self._crop_min_y_val = None
        self._crop_max_y_val = None
        # Note on the difference between self._maxy and
        # self._crop_max_y_val: self._maxy is always the maximum shown
        # y-value. self._crop_max_y_val is only the maximum (and then
        # the same than self._maxy) if plot_bands was called with a
        # crop_y argument set to a y-value or to True, otherwise
        # self._crop_max_y_val will still be None. If another graph is
        # added with plot_bands while self._crop_max_y_val is set, the
        # minimum of the new graph's crop_y value and the old value will
        # be used as new maximum. If self._crop_max_y_val is still None
        # in that case, the y-axis will be scaled to show the maximum of
        # all graphs.
        # The same goes for the minimum values.

        # start new plot at blue again (using the seaborn default color 
        # palette with red and green exchanged to meet common conventions):
        self._colors = cycle([(0.2980392156862745, 0.4470588235294118, 
                               0.6901960784313725),
                              (0.7686274509803922, 0.3058823529411765, 
                               0.3215686274509804),
                              (0.3333333333333333, 0.6588235294117647, 
                               0.40784313725490196),
                              (0.5058823529411764, 0.4470588235294118, 
                               0.6980392156862745),
                              (0.8, 0.7254901960784313, 
                               0.4549019607843137),
                              (0.39215686274509803, 0.7098039215686275, 
                               0.803921568627451)])
        self._last_color = (0.2980392156862745, 0.4470588235294118, 
                            0.6901960784313725)
        self._distribute_subplots()

    def set_num_rows(self, numrows):
        """Change the number of subplot rows.

        Multiple subplots will be distributed so they occupy numrows rows.
        """
        self._numrows = max(numrows, 1)
        self._distribute_subplots()

    def _distribute_subplots(self):
        """Redistribute subplots so they occupy the set number of rows."""
        rows = max(self._numrows, 1)
        if self._numrows == 0:
            numcols = 1
            rows = self._numplots
        else:
            numcols = int(np.ceil(self._numplots / rows))
            rows = min(rows, self._numplots)

        for i, ax in enumerate(self._axes):
            ax.change_geometry(rows, numcols, i + 1)
    
    def _calc_corrected_x_values(self, k_data):
        """Calculate new x-axis values based on the Euclidean point
        distance of the k-vectors."""
        def point_distance(p1, p2):
            """Euclidean point distance in 3D space"""
            return np.sqrt(np.sum(np.square(p2 - p1)))
        
        x_vals = np.zeros(len(k_data))
        k_data_vecs = k_data[:, :-1]  # the kmag/2pi column is irrelevant here
        for i, k in enumerate(k_data_vecs[:-1]):
            x_vals[i + 1] = point_distance(k, k_data_vecs[i + 1]) + x_vals[i]
        return x_vals
    
    def plot_bands(
            self, banddata, k_data, formatstr='',
            x_axis_formatter=CustomAxisFormatter(),
            crop_y=True, picker=3, label=None,
            correct_x_axis=defaults.correct_x_axis,
            color_by_parity=False, **kwargs):
        """Plot bands. plt.show() must be called to actually show the figure
        afterwards.

        *banddata* has columns for each band to be plotted and a row for each
        k_vector.
        The four columns of *k_data* must correspond to kx-, ky-,
        kz-components and magnitude of the k-vectors.
        *banddata* and *k_data* must have same amount of rows.

        *formatstr* is the format string forwarded to the pyplot.plot command.

        *x_axis_formatter* is an object with the method
        'apply_to_axis(axis, **kwargs)' which sets the x-axis' tickpositions,
        major ticklabels and label. The default is CustomAxisFormatter() with
        no major ticks.

        If *crop_y* is true (default), the y-axis (frequency) will be limited
        so that only frequency values are shown where all bands are known.
        Alternatively, a numeric value of crop_y denotes the upper frequency
        value where the plot will be cropped, or if *crop_y* is a
        2-tuple, it denotes the minimum and maximum y-value.

        *picker* (default: 3) is a radius in pixels around the cursor position
        of a mouse click event in the plot. Any vertex inside this radius will
        trigger the onclick function supplied when the Bandplotter object was
        created. Multiple vertices inside this radius will not trigger multiple
        function calls, but the event.ind list supplied to the function will
        contain the data indices of all these vertices.

        The *label* is the graph's label. It will be shown in a plot legend if
        one is added.
        
        If *correct_x_axis* is set to True (default), the bands are plotted
        versus x-values which are equidistant according to the Euclidean
        distance between the k-vectors. That way distortions are avoided which
        occur when plotting versus the k-index.

        :param color_by_parity: If not False, provide the parity data as
        numpy array with the same shape as banddata

        All other keyword arguments *kwargs* will be forwarded to the
        matplotlib plot function.

        """
        if len(banddata) == 0:
            return

        # If plot_bands has been called before in this subplot, self._x_data
        # will be set. In that case, the user can't change his mind anymore
        # whether he want to correct the x-axis or not:
        if self._x_data is not None:
            if correct_x_axis != self._x_axis_corrected:
                log.warning("bandplotter.plot_bands: In a previous call to "
                            "plot_bands, correct_x_axis had a differnt value "
                            "than in this call. The previous value will be "
                            "used again.")
                correct_x_axis = self._x_axis_corrected

        # Keep reference to last banddata for add_light_cone,
        # fill_between_bands and maybe other:
        self._x_data = np.arange(len(banddata))
        self._last_data = banddata
        self._last_kdata = k_data

        if color_by_parity is False:
            color_by_parity = None
        if color_by_parity is not None:
            if banddata.shape != color_by_parity.shape:
                log.warning(
                    "color_by_parity's shape ({0}) does not match "
                    "that of banddata ({1}). Will not color by "
                    "parity.".format(
                        color_by_parity.shape, banddata.shape))
                color_by_parity = False

        if crop_y:
            if crop_y is True:
                # Automatic cropping: Crop to just below the last band:
                crop_y = banddata[:,-1].min()

            if hasattr(crop_y, '__len__') and len(crop_y) == 2:
                newmin = crop_y[0]
                newmax = crop_y[1]
            else:
                newmin = None
                newmax = crop_y

            if self._crop_max_y_val is None:
                # Was not cropped before:
                self._crop_max_y_val = newmax
            else:
                # Another graph in the same subplot is cropped, use minimum:
                self._crop_max_y_val = min(self._crop_max_y_val, newmax)

            if newmin is not None:
                if self._crop_min_y_val is None:
                    # Was not cropped before:
                    self._crop_min_y_val = newmin
                else:
                    # Another graph in the same subplot is cropped, use
                    # maximum:
                    self._crop_min_y_val = max(self._crop_min_y_val, newmin)

        if self._crop_max_y_val is None:
            # Neither this graph nor any other in this subplot need to be
            # cropped, so set y-axis' maximum to maximum of data:
            self._maxy = max(self._maxy, banddata.max())
        else:
            self._maxy = self._crop_max_y_val

        if self._crop_min_y_val is None:
            # Neither this graph nor any other in this subplot need to be
            # cropped, so set y-axis' minimum to minimum of data:
            self._miny = min(self._miny, banddata.min())
        else:
            self._miny = self._crop_min_y_val

        if (not 'color' in kwargs and not 'c' in kwargs and
                _process_plot_format(formatstr)[-1] is None):
            # if no color for the plot is given, use automatic coloring:
            kwargs['color'] = next(self._colors)

        if 'c' in kwargs:
            self._last_color = kwargs['c']
        else:
            self._last_color = kwargs['color']


        if correct_x_axis:
            # we need to update the reference to the x_data and the
            # x_axis_formatter ticks accordingly to get the lightcone and the
            # x-axis labels right
            x_vals = self._calc_corrected_x_values(k_data)
            tick_pos = x_axis_formatter.get_tick_positions()
            # only need to correct x-axis ticks once:
            if not self._x_axis_corrected:
                if tick_pos.dtype != np.int32:
                    log.warning(
                        "bandplotter.plot_bands: Cannot correct x-axis. "
                        "It seems the x_axis_formatter is customized "
                        "with non-integer tick positions.")
                else:
                    x_axis_formatter.tweak_tick_positions(x_vals[tick_pos])
                    self._x_axis_corrected = True

            # only continue if the x-axis' correction was successful:
            if self._x_axis_corrected:
                self._x_data = x_vals

        self._ax.plot(
            self._x_data, banddata, formatstr, label=label, **kwargs)
        if color_by_parity is not None:
            for i, bd in enumerate(banddata.T):
                self._last_parity_scatter = self._ax.scatter(
                    self._x_data,
                    bd,
                    s=defaults.color_by_parity_marker_size,
                    label=label,
                    zorder=100,
                    c=color_by_parity[:, i],
                    vmin=-1, vmax=1,
                    cmap='bwr',
                    **kwargs)

        # get kwargs for ticklabel formatting:
        if (x_axis_formatter.get_longest_label_length() >
            defaults.long_xticklabels_when_longer_than):
                kwargs = defaults.long_xticklabels_kwargs
        else:
                kwargs = defaults.xticklabels_kwargs

        # set x axis ticks, ticklabels and axis label:
        x_axis_formatter.apply_to_axis(
            self._ax.get_xaxis(), **kwargs)

        if picker:
            # add invisible dots for picker
            # (if picker added to plots above, the lines connecting the dots
            # will fire picker event as well) - this is ok if no dots are shown
            # Also, combine banddata so it is in one single dataset. This way,
            # the event will fire only once, even when multiple dots coincide:
            # (but then with multiple indices)
            xnum, bands = banddata.shape
            newdata = np.zeros((5, xnum * bands))
            for i, x in enumerate(self._x_data):
                for j, y in enumerate(banddata[i, :]):
                    if color_by_parity is None:
                        pardata = np.nan
                    else:
                        pardata = color_by_parity[i, j]
                    newdata[:, i + xnum*j] = [x, y, i, j, pardata]

            frmt = 'o'
            if not ('o' in formatstr or '.' in formatstr):
                frmt += '-'
            line, = self._ax.plot(
                newdata[0], newdata[1], frmt, picker=picker, alpha=0,
                label=label, zorder=1000)
            # attach data, so it can be used in picker callback function:
            line.data = newdata

        # matplotlib sometimes adds padding; remove it:
        self._ax.set_xlim(min(self._x_data), max(self._x_data))
        # but only remove y-padding if y-data must be cropped:
        if (self._crop_max_y_val is not None or
            self._crop_min_y_val is not None):
                self._ax.set_ylim(self._miny, self._maxy)


    def plot_dos(self, dos, freqs):
        """Plot density of states in the current subplot."""
        self._ax.plot(dos, freqs)
        self._ax.set_xlabel('DOS', size='x-large')
        self._ax.set_ylabel('')

        # matplotlib sometimes adds padding; remove it:
        self._ax.set_xlim(min(self._x_data), max(self._x_data))
        # but only remove y-padding if y-data must be cropped:
        if (self._crop_max_y_val is not None or
            self._crop_min_y_val is not None):
                self._ax.set_ylim(self._miny, self._maxy)


    def add_light_cone(
            self, index_of_refraction=1, color='gray', alpha=0.5):
        """Add a light cone to the current subplot.

        Only works if plot_bands have been called before on this subplot.
        """
        if self._last_kdata is None:
            raise ValueError(
                'cannot add light cone: '
                'k_data not given in last plot_bands()')
        if alpha:
            fillto = 1.1 * max(
                self._last_kdata[:, 3].max() / index_of_refraction,
                self._ax.get_ylim()[1])
            # As of Python version 3.4.3 and Matplotlib version 1.5.1, there is
            # a bug in Axes.fill_between, which, in certain cases (especially
            # when tight_layout is used or briefly just by moving the plot
            # area around in the window), uses so much CPU power and memory
            # during rendering, that the computer gets unresponsive. I found
            # no such problems when using Python 2.7.6 with the same Matplotlib
            # version. Therefore, I will use Axes.fill instead of fill_between,
            # even though it seems overly complicated.
            ## buggy:
            ##self._ax.fill_between(
            ##    self._x_data, self._last_kdata[:, 3],
            ##    fillto,
            ##    color=color, alpha=alpha)
            fill_x_data = np.append(
                self._x_data, [self._x_data[-1], self._x_data[0]])
            fill_y_data = np.append(
                self._last_kdata[:, 3] / index_of_refraction,
                [fillto, fillto])
            self._ax.fill(
                fill_x_data, fill_y_data,
                color=color, alpha=alpha)

        self._ax.plot(
            self._x_data,
            self._last_kdata[:, 3] / index_of_refraction,
            color=color)

        # matplotlib sometimes adds padding; remove it:
        self._ax.set_xlim(min(self._x_data), max(self._x_data))
        # but only remove y-padding if y-data must be cropped:
        if (self._crop_max_y_val is not None or
            self._crop_min_y_val is not None):
                self._ax.set_ylim(self._miny, self._maxy)


    def add_filled_polygon(
            self, points, color=None, alpha=0.35, gap_text=''):
        """Add a band gap polygon to the current subplot.

        Add a polygon with the vertices *points* (a list of 2-tuples).
        If *color* is None (default), use the color of the last plotted bands.
        *alpha* is the opacity of the rectangle.
        If *gap_text* is a string, adds the text
        (formatted with format(gapsize_in_percent)) to the center of the
        polygon.

        """
        if len(points) == 0:
            return
        if color is None:
            #use color of last plotted data:
            color = self._last_color

        points=np.array(points)
        self._ax.add_patch(
            mpl.patches.Polygon(points, color=color, alpha=alpha,
                                linewidth=0.5))
        # Get polygon's center to place text:
        mx = points.max(axis=0)
        mn = points.min(axis=0)
        h = mx[1] - mn[1]
        center = (mx[1] + mn[1]) / 2
        gapsize = h / center
        xcenter = (mx[0] + mn[0]) / 2
        gaptext = gap_text.format(gapsize * 100)
        self._ax.add_artist(
            mpl.text.Text(text=gaptext,
                        x=xcenter, y=center,
                        horizontalalignment='center',
                        verticalalignment='center'))

    def add_band_gap_rectangle(
            self, from_freq, to_freq, color=None, alpha=0.35,
            light_line=None):
        """Add a band gap rectangle to the current subplot.

        Add a rectangle between the frequencies *from_freq* and *to_freq*.
        If *color* is None (default), use the color of the last plotted bands.
        *alpha* is the opacity of the rectangle.
        If *light_line* is given (a list of frequencies, it is important to
        supply exactly one frequency for each k-vector in the right order),
        the rectangle will be clipped under the light line.

        Note: This implementation supports clipping even if the light line
        splits the bandgap into multiple parts.

        """
        if from_freq < 0 or to_freq <= 0:
            return

        left = min(self._x_data)
        right = max(self._x_data)

        if light_line is None:
            # add a rectangle not clipped by light line:
            self.add_filled_polygon(
                points=[(left, from_freq), (right, from_freq),
                        (right, to_freq), (left, to_freq)],
                color=color,
                alpha=alpha,
                gap_text=defaults.default_gaptext)
        else:
            # light line provided, crop bandgap box at light line:

            # We walk through the light line frequencies, and check at each
            # index (i.e. at each k-vector) whether the light freq is above
            # to_freq or below from_freq. If both are false, the light freq is
            # in between, naturally.
            #
            # While going from one index to the next, if there is a transition
            # from not above to above or vice versa, or from not below to below
            # or vice versa, we calculate the intersection point and add it to
            # the list of polygon points, together with the light freq points
            # in between and the points on the corners of the bandgap box.
            #
            # Each time the light line enters the gap box from the bottom, we
            # start a new polygon, and each time the light line leaves the
            # bottom, we are finished with a polygon and add it to the plot.

            above = light_line[0] >= to_freq
            below = light_line[0] <= from_freq
            points = []

            if not below:
                points.append((self._x_data[0], from_freq))
                if above:
                    points.append((self._x_data[0], to_freq))
                else:
                    points.append((self._x_data[0], light_line[0]))

            for i in range(1, len(light_line)):
                x0 = self._x_data[i - 1]
                xd = self._x_data[i] - x0

                prev_below = below
                prev_above = above
                above = light_line[i] >= to_freq
                below = light_line[i] <= from_freq

                # The order of the following checks and appends is important.

                # Check for transitions to inside, add intersections if needed:
                if prev_above and not above:
                    points.append((
                        x0 + xd * get_intersection_knum(
                            light_line[i - 1], light_line[i], to_freq),
                        to_freq))
                elif prev_below and not below:
                    # Here we actually start a new polygon, but the points
                    # list should already be empty at this stage.
                    points.append((
                        x0 + xd * get_intersection_knum(
                            light_line[i - 1], light_line[i], from_freq),
                        from_freq))
                # Add point if light freq is in between:
                if not above and not below:
                    points.append((self._x_data[i], light_line[i]))
                # Check for transitions to outside, add intersections if needed:
                elif not prev_above and above:
                    points.append((
                        x0 + xd * get_intersection_knum(
                            light_line[i - 1], light_line[i], to_freq),
                        to_freq))
                elif not prev_below and below:
                    # Here we close the polygon.
                    points.append((
                        x0 + xd * get_intersection_knum(
                            light_line[i - 1], light_line[i], from_freq),
                        from_freq))
                    # Add the polygon to the plot:
                    self.add_filled_polygon(
                        points=points,
                        color=color,
                        alpha=alpha,
                        gap_text=defaults.default_gaptext)
                    # And now empty the points list:
                    points = []

                # Note that we add nothing if (prev_below and below) or if
                # (prev_above and above).

            # After we walked through the light line frequencies, we still
            # might need to close the polygon at right side:
            if above:
                points.append((right, to_freq))
            if not below:
                points.append((right, from_freq))

            # Add the polygon to the plot:
            self.add_filled_polygon(
                points=points,
                color=color,
                alpha=alpha,
                gap_text=defaults.default_gaptext)


    def add_continuum_bands(
            self, data, color=None, alpha=0.65,
            prevent_overlapping=True):
        """Add continuum (projected) bands to the current subplot.

        :param data: a (num_k-vecs x 2*num_conti_bands)-array. The 1st
        axis has exactly the same size as there are k-vectors in this
        plot. The 2nd axis' length is even: the first column holds the
        minimum frequencies of the first continuum band, the second line
        its maximum frequencies, and so on for more bands.
        :param color: If this is None (default), use the color of the last
        plotted bands, otherwise, use this color.
        :param alpha: The opacity of the bands.
        :param prevent_overlapping: if multiple bands overlap, it looks
        too full if they are half-transparent. This prevents this.

        """
        numk = len(self._x_data)
        if (not data.shape[0] == numk or
                not data.shape[1] % 2 == 0):
            log.warning('data supplied to bandplotter.add_continuum_bands '
                        'is malformed.')
            return
        numbands = data.shape[1] // 2

        if prevent_overlapping:
            intersection_points = []
            for b in range(1, numbands):
                prev_above=False
                prev_f=0
                for k in range(numk):
                    if data[k, 2 * b] < data[k, 2 * b - 1]:
                        # higher band's bottom is BELOW lower band's top
                        if prev_above and k != 0:
                            # calculate intersection:
                            ipt = get_intersection(
                                freq_left1=prev_f,
                                freq_right1=data[k, 2 * b],
                                freq_left2=data[k - 1, 2 * b - 1],
                                freq_right2=data[k, 2 * b - 1]
                            )
                            intersection_points.append(
                                (b, ipt[0] + k - 1, ipt[1]))
                        prev_above = False
                        prev_f = data[k, 2 * b]
                        data[k, 2 * b] = data[k, 2 * b - 1]
                    else:
                        # higher band's bottom is ABOVE lower band's top
                        if not prev_above and k != 0:
                            # calculate intersection:
                            ipt = get_intersection(
                                freq_left1=prev_f,
                                freq_right1=data[k, 2 * b],
                                freq_left2=data[k - 1, 2 * b - 1],
                                freq_right2=data[k, 2 * b - 1]
                            )
                            intersection_points.append(
                                (b, ipt[0] + k - 1, ipt[1]))
                        prev_f = data[k, 2 * b]
                        prev_above = True

        for i in range(numbands):
            # create a polygon for each conti band:

            ipts = []
            if prevent_overlapping:
                # is there an intersection point to add in this band?
                for j, (b, k, f) in reversed(list(enumerate(
                        intersection_points))):
                    if b == i:
                        ipts.append((k, f))
                        del intersection_points[j]

            pts = []
            for k, x in enumerate(self._x_data):
                if prevent_overlapping:
                    # do we need to add an intersection point first?
                    for j, (ki, fi) in reversed(list(enumerate(ipts))):
                        if k > ki:
                            pts.append(
                                (self._x_data[k - 1] * (k - ki) +
                                    self._x_data[k] * (ki - k + 1),
                                 fi)
                            )
                            del ipts[j]

                pts.append((x, data[k, 2 * i]))
            for k, x in reversed(list(enumerate(self._x_data))):
                pts.append((x, data[k, 2 * i + 1]))
            # add a rectangle not clipped by light line:
            self.add_filled_polygon(
                points=pts,
                color=color,
                alpha=alpha)


    def fill_between_bands(
            self, bandfrom, bandto, color = '#7f7fff', alpha=0.5):
        """ FIXME: see add_light_cone comments: fill_between is unstable, needs
        to be changed to use Axes.fill! In the mean time, don't use this
        function with Python3! Python 2.7 works fine.
        """
        self._ax.fill_between(
            self._x_data, self._last_data[:, bandfrom - 1],
            self._last_data[:, bandto - 1],
            color=color, alpha=alpha)

        # matplotlib sometimes adds padding; remove it:
        self._ax.set_xlim(min(self._x_data), max(self._x_data))
        if self._crop_max_y_val is not None:
            # but only remove y-padding if y-data must be cropped:
            self._ax.set_ylim(self._miny, self._maxy)


    def add_legend(self, loc = 'upper left'):
        handles, labels = self._ax.get_legend_handles_labels()
        filteredlabels = []
        filteredhandles = []
        # filter labels, so each one occurs only once
        # (otherwise legend is too crowded)
        for i, label in enumerate(labels):
            if not label in filteredlabels:
                filteredlabels.append(label)
                filteredhandles.append(handles[i])
        plt.legend(filteredhandles, filteredlabels, loc=loc)


    def add_color_bar_for_parity(self, parity_direction='z',
                                 location='right', pad=0.1):
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        """Add a color bar for the parity color code to the current axis.

        :param parity_direction: is only needed for the label.
        :param location: can be 'left', 'right', 'top' or 'bottom'
        :param pad: the padding between the current axis and the new
        colorbar, in inches.

        """
        if self._last_parity_scatter is None:
            # no parity data plotted
            return

        # create an axes on the side of self._ax. cax will take 5% of
        # self._ax and the padding between cax and self._ax will be
        # fixed at *pad* inch.
        divider = make_axes_locatable(self._ax)
        cax = divider.append_axes(location, size="5%", pad=pad)

        if location in ['top', 'bottom']:
            orientation='horizontal'
        else:
            orientation='vertical'

        cb = plt.colorbar(
            self._last_parity_scatter,
            cax=cax,
            orientation=orientation,
            ticklocation=location)
        cb.set_label('{0}-parity'.format(parity_direction))


    def add_image_inset(self, filename, loc=4, zoom=1, transpose=False):
        """
        Add a raster image to the plot, according to the legend location loc.
        :param filename: image's file name
        :param loc: an integer specifying the location.
        The valid location codes are:
            'upper right'  : 1,
            'upper left'   : 2,
            'lower left'   : 3,
            'lower right'  : 4,
            'right'        : 5,
            'center left'  : 6,
            'center right' : 7,
            'lower center' : 8,
            'upper center' : 9,
            'center'       : 10,
        :param zoom: scaling factor of the image
        :param transpose: Transpose the image.

        """
        arr_eps = plt.imread(filename)
        if transpose:
            arr_eps = arr_eps.transpose((1, 0, 2))
        imagebox = OffsetImage(arr_eps, zoom=zoom)
        ab = AnchoredOffsetbox(loc=loc, child=imagebox, frameon=False)
        self._ax.add_artist(ab)


    def set_plot_title(self, title):
        self._ax.set_title(title, size='x-large')


    def savefig(self, *args, **kwargs):
        # set tight_layout after everything (title, labels, other subplots)
        # have been added:
        self._fig.tight_layout()
        return self._fig.savefig(*args, **kwargs)


    def show(self, block=True, tight=True):
        # set tight_layout after everything (title, labels, other subplots)
        # have been added:
        if tight:
            plt.tight_layout()
        plt.show(block=block)
