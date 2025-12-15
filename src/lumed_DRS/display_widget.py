import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT, FigureCanvasQTAgg
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget
from matplotlib.figure import Figure

# this tutorial is great: https://www.pythonguis.com/tutorials/plotting-matplotlib/

class DataDisplayWidget(QWidget):
    """Widget to display DRS and raman data on Lumed_DRS_widget"""

    def __init__(self, parent=None):

        super().__init__(parent)
        fig = Figure(figsize=(5, 5))
        self.canvas = FigureCanvasQTAgg(fig)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.ax = self.canvas.figure.add_subplot(111)
        self.ax.set_facecolor('dimgray')
        self.canvas.figure.patch.set_facecolor('dimgray')
        self.canvas.figure.subplots_adjust(left=0.1, right=0.97, top = 0.97)
        self._plot_ref = None
    def plot_basic_line(self, x, y, label, xlim=None):
        corrected = np.nan_to_num(y, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        self.ax.plot(x, y, label=f"{label}")
        self.ax.set_xlabel("wavelength (nm)")
        self.ax.set_ylabel("intensity")
        # Set x axis
        if xlim != None:
            self.ax.set_xlim(xlim, x[-1])
            # new x limits
            x_min, x_max = self.ax.get_xlim()
            # Filter the data based on x limits
            mask = (x >= x_min) & (x <= x_max)
            y_visible = corrected[mask]
            # Adjust y-axis limits based on visible data
            spacing = 0.05 * (y_visible.max() - y_visible.min())
            self.ax.set_ylim(y_visible.min() - spacing, y_visible.max() + spacing)
        # Refresh canvas
        self.ax.legend()
        self.canvas.draw()

    def add_plot(self, xdata, ydata, labels:list = None):
        self._plot_ref, = self.ax.plot(xdata, ydata)
        if labels is not None:
            self.ax.legend(labels)
    
    def update_plot(self, xdata, ydata, labels:list = None):
        colors = plt.cm.jet(np.linspace(0,1,ydata.shape[1])) # color gradient definition
        if self._plot_ref is None: 
            self._plot_ref = []
            for i in range(ydata.shape[1]):
                self._plot_ref.append(self.ax.plot(xdata, ydata[:,i], color=colors[i], labels = labels[i])) # if first time plotting call plot method
        elif len(self.ax.lines) >= ydata.shape[1]:
            #if number of lines is higher or equal than the newer data we want to plot
            N = ydata.shape[1]# Number of new line plots
            #print('len(self._plot_ref):', len(self._plot_ref), 'ydata.shape[1]:', ydata.shape[1])
            #Trim lines that are in excess
            for line in self.ax.lines[N:]:
                line.remove()
            # Set data in lines that remain with the new data
            for i in range(len(self.ax.lines)):
                print('i:', i, "label:", labels[i])
                self.ax.lines[i].set_ydata(ydata[:,i]) #update y data of plot instead of clearing the axes (faster)
                self.ax.lines[i].set_color(colors[i])
                if labels is not None:
                    self.ax.lines[i].set_label(labels[i]) 

        elif len(self.ax.lines) < ydata.shape[1]:
            #if number of lines is lower than the newer data we want to plot
            for i in range(ydata.shape[1]):
                if i >= len(self.ax.lines):
                    # plot new lines for indexes that exceed the previous plot
                    self.ax.plot(xdata, ydata[:,i], color = colors[i])
                    if labels is not None:
                        self.ax.lines[i].set_label(labels[i])
                else:
                    #update y data of plot instead of clearing the axes (faster)
                    self.ax.lines[i].set_ydata(ydata[:,i]) 
                    self.ax.lines[i].set_color(colors[i])
                    if labels is not None:
                        self.ax.lines[i].set_label(labels[i])
        if labels is not None:
            self.ax.legend() # Tell matplotlib to refresh the legend
        self.ax.relim() # Recompute the data limits based on current artists (from documentation)
        self.ax.autoscale()
        self.canvas.draw()