import sys
import time as tt
import traceback
import threading
from threading import Thread

from PyQt5.QtCore import QObject, QThread, QRunnable, pyqtSignal, pyqtSlot


class CustomThread(Thread):
    def __init__(self, group=None, target=None, name=None,
                 args=(), kwargs={}, Verbose=None):
        Thread.__init__(self, group, target, name, args, kwargs)
        self._return = None
 
    def run(self):
        if self._target is not None:
            self._return = self._target(*self._args, **self._kwargs)
             
    def join(self, *args): # .join() method of Thread being overwritten to return
        Thread.join(self, *args)
        return self._return

class WorkerSignals(QObject):
    """Signals from a running worker thread.

    finished
        No data

    error
        tuple (exctype, value, traceback.format_exc())

    result
        object data returned from processing, anything

    progress
        float indicating % progress
    """

    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(float)

class WorkerThread(QRunnable):
    """
    Class defining a worker thread.
    """
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs) # run the functon to be run by the thread
            self.signals.result.emit(result)
        except Exception:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()

class LoopWorkerThread(QRunnable):
    """
    Class defining a worker thread.
    """
    def __init__(self, func, *args, interval: float = 0.5,  **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.interval = float(interval)
        self._stop_event = threading.Event()
    
    def stop(self):
        """Request the loop to stop from another thread (main thread)."""
        self._stop_event.set()
    
    @pyqtSlot()
    def run(self):
        try:
            # result  = False
            n = 0
            previous_result = None 
            
            while not self._stop_event.is_set():
                try:
                    result = self.func(*self.args, **self.kwargs) # run the functon to be run by the thread
                    if result != previous_result:
                        #print('previous_result:', previous_result, ', result:', result)
                        self.signals.result.emit(result)
                        previous_result = result
                        # print(f"worker loop time: {tt.time() - tic} changed!")
                except Exception as e:
                    # emit error but continue or break as appropriate
                    self.signals.error.emit((type(e), e, traceback.format_exc()))
                n += 1
                #wait but return immediately if stop() function is called
                self._stop_event.wait(self.interval)
        except Exception:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        finally:
            self.signals.finished.emit()
       