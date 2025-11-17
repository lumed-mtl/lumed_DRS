# ..oo00OO00oo..
import sys
import time
import math
import sklearn

import numpy as np
import pandas as pd

from scipy.signal import find_peaks, argrelextrema
from scipy.interpolate import interp1d, UnivariateSpline

from sklearn.metrics import auc, roc_curve, confusion_matrix
from sklearn.svm import SVC, LinearSVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectFromModel
#from xgboost.sklearn import XGBClassifier
from orpl.baseline_removal import bubblefill

def blood_cont(signal, xaxis):
    '''
    Compute the blood contamination of an input signal

    Parameters
    ----------
    signal: ndarray of shape (n_features,)
        Input signal
    xaxis: ndarray of shape (n_features,)
        Input signal's xaxis
        
    Returns
    -------
    float
        Blood contamination computed from signal
    '''
    x1, y1 = 0.9999170471, 1
    x2, y2 = -0.881303, 0
    m = (y2 - y1) / (x2 - x1)
    b = y1 - m * x1
    SAM = sam(signal, xaxis, 'blood')
    return float(m * SAM + b)
    
def sam(signal, xaxis, ref_type):
    '''
    Compute the sam of an input signal with a reference

    Parameters
    ----------
    signal: ndarray of shape (n_features,)
        Input signal
    xaxis: ndarray of shape (n_features,)
        Input signal's xaxis
    ref_type: string of type: 'blood', 'bone', 'fat'
    
    Returns
    -------
    sam: float
        SAM value computed from input signals
    '''
    # Select biomarkers based on reference tissue type:
    if ref_type == 'bone':
        biomarkers = [(930, 980)]
    elif ref_type == 'blood':
        biomarkers = [(1200, 1242), (1520, 1637)]
    elif ref_type == 'fat':
        biomarkers = [(1285, 1325)]
    else:
        raise ValueError("Invalid reference spectra.")
    
    # Interpolate input signal:
    MIN_CM1 = 650
    MAX_CM1 = 1790
    new_xaxis = np.linspace(MIN_CM1, MAX_CM1, num=MAX_CM1-MIN_CM1+1)
    new_signal = interpolate(xaxis, signal, new_xaxis)
    
    # Load reference spectra:
    ref_df = pd.read_pickle('datasets.pkl')
    df = ref_df[ref_df.label == ref_type]
    ref = np.array([s for s in df.raman.values]) # [[dataset1],[dataset2],...[datasetN]]
    ref = np.mean(ref, axis=0) # average spectra
    
    # Filter signals and xaxis to match biomarkers range:
    filtered_xaxis = np.array([], dtype=new_xaxis.dtype)
    filtered_signal = np.array([], dtype=new_signal.dtype)
    filtered_ref = np.array([], dtype=ref.dtype)
    for start, end in biomarkers:
        indices = (new_xaxis >= start) & (new_xaxis <= end)
        filtered_xaxis = np.concatenate((filtered_xaxis, new_xaxis[indices]))
        filtered_signal = np.concatenate((filtered_signal, new_signal[indices]))
        filtered_ref = np.concatenate((filtered_ref, ref[indices]))
    new_xaxis, new_signal, new_ref = filtered_xaxis, filtered_signal, filtered_ref
    
    # Calculate SAM:
    numerator = np.dot(new_signal, new_ref)
    denominator = np.linalg.norm(new_signal) * np.linalg.norm(new_ref)
    cos_theta = np.clip(numerator / denominator, -1.0, 1.0)
    sam_rad = np.arccos(cos_theta) # arccos -> values from 0 to pi
    sam_deg = np.degrees(sam_rad) # convert to degrees -> 0 to 180 deg.
    return cos_theta

def snv(x):
    '''
    Standard normal variate normalization of an input signal

    Parameters
    ----------
    x: ndarray
        If one-dimensional, ndarray of shape (n_features,)
        If two-dimensional, ndarray of shape (n_samples, n_features)

    Returns
    -------
    ndarray
        Normalized signal, same dimension as input
    '''
    if x.ndim == 1:
        return (x - np.mean(x))/np.std(x)
    elif x.ndim == 2:
        return (x - np.mean(x, axis=1)[:, np.newaxis]) / np.std(x, axis=1)[:, np.newaxis]
    
def quality_factor(signal):
    '''
    Compute the quality factor of an input signal

    Parameters
    ----------
    signal: ndarray of shape (n_features,)
        Input signal

    Returns
    -------
    qf: float
        Quality factor computed from signal
    '''
    signal_ = snv(signal)
    deviation_sign = np.sign(signal_)
    deviation2 = (signal_ - signal_.mean()) ** 2
    qf = (deviation_sign * deviation2).mean()
    return qf

def interpolate(xaxis, y, xnew):
    '''
    Interpolates and transforms a 1-D signal to a specified new set of coordinates

    Parameters
    ----------
    xaxis: ndarray of shape (n_features,)
        Wavenumbers in cm-1
        
    y: ndarray of shape (n_features,)
        Intensities associated with the bins of xaxis

    xnew: ndarray
        New set of xaxis coordinates where min and max must be within
        the original range of xaxis

    Returns
    -------
    ynew: ndarray
        Intensities corresponding to the new set of coordinates
    '''
    f = interp1d(xaxis, y)
    ynew = f(xnew)
    return ynew

def get_xarg(xaxis=np.ndarray, x0=float):
    '''
    Finds the array index closest to a specified value

    Parameters
    ----------
    xaxis: ndarray of shape (n_features,)
        Wavenumbers in cm-1

    x0: float
        Value to search in xx

    Returns
    -------
    xarg: int
        Index position in xaxis closest to x0
    '''
    return np.argmin(np.abs(xaxis-x0))

def get_correction_curve(x, nist):
    A0 = 9.71937e-02;
    A1 = 2.28325e-04;
    A2 = -5.86762e-08;
    A3 = 2.16023e-10;
    A4 = -9.77171e-14;
    A5 = 1.15596e-17;

    n0 = A0
    n1 = A1*x
    n2 = A2*x**2
    n3 = A3*x**3
    n4 = A4*x**4
    n5 = A5*x**5
    nist_theo = n0+n1+n2+n3+n4+n5

    curve = nist/nist_theo

    return curve/np.nanmax(curve)

def peak_subset(xx, hei, pos, std, full_width=1/2, plot_gaus=True):
    all_roots = []
    for a0,x0,s0 in zip(hei,pos,std):
        gaus_y = pdf_gaus(xx,a0,x0,s0)
        if plot_gaus:
            ax.plot(xx, gaus_y, color='grey')
        spline = UnivariateSpline(xx, gaus_y-a0*(full_width), s=0)
        rr = spline.roots()
        r1 = rr[np.where(rr<x0)][-1]
        r2 = rr[np.where(rr>x0)][0]
        all_roots.append(r1)
        all_roots.append(r2)
    all_roots = np.array(all_roots)
    xarg = np.concatenate((argrelextrema(all_roots, np.less)[0], argrelextrema(all_roots, np.greater)[0]))
    all_roots = np.delete(all_roots, xarg)
    
    new_roots = np.array([np.argmin(np.abs(xx-s)) for s in all_roots])
    feature_set = np.concatenate([np.arange(x0,x1) for x0,x1 in zip(new_roots[0::2],new_roots[1::2])])
    return feature_set, new_roots

def progressbar(it, prefix='Progress: ', out=sys.stdout, start=time.time()):
    '''
    Super cool progress bar

    source: https://stackoverflow.com/questions/3160699/python-progress-bar
    '''
    count = len(it)
    size = 20
    def show(j,p,x):
        if x != size:
            print("{}|{}{}| {}/{} [{}%] in {:.0f}s".format(prefix, u'█'*x, ' '*(size-x), j, count, p, time.time()-start), 
                  end='\r', file=out, flush=True)
        else:
            print("{}|{}{}| {}/{} [{}%] in {:.1f}s".format(prefix, u'█'*x, ' '*(size-x), j, count, p, time.time()-start), 
                  end='\r', file=out, flush=True)
    show(0,0,0)
    cpt = 0
    for i, item in enumerate(it):
        yield item
        pct = int((i+1)/count*100)
        dis = int(pct//(100/size))
        show(i+1,pct,dis)
    print("\n", flush=True, file=out)

def get_kpeaks(x_mat, y_mat,width, prom=None, hei=None):

    bits = np.zeros((1, np.round(np.max(x_mat)+1).astype(int)),dtype= int)[0]      # initialize count array

    if y_mat.ndim != 1:
        nrow_y_mat=y_mat.shape[0]
    else:
        nrow_y_mat = 1
    for i in np.arange(0,nrow_y_mat):

        if x_mat.ndim != 1:
            spectra_x = x_mat[i]
        else:
            spectra_x = x_mat
        if y_mat.ndim != 1:
            spectra_y = y_mat[i]
        else:
            spectra_y = y_mat

        ps = find_peaks(spectra_y, prominence = prom, height = hei)[0]

        r_shift = np.round(spectra_x[ps]).astype(int)
        bits[r_shift] = bits[r_shift] + 1


    add_peaks=[]
    for i in range(2,len(bits) - 2):
        range_normal=range(i-2,i+3,1)
        range_narrow=range(i-1,i+2,1)
        range_2left=range(i-1,i,1)
        range_2right=range(i,i+2,1)
        if ((np.round(np.sum(bits[range_normal])/nrow_y_mat,3) >0.50) or
                (bits[i]/nrow_y_mat>0.01 and np.round(np.sum(bits[range_2right])/nrow_y_mat,3)>0.30) or
                (bits[i]/nrow_y_mat>0.01 and np.round(np.sum(bits[range_2left])/nrow_y_mat,3)>0.30) or
                (np.round(np.sum(bits[range_narrow])/nrow_y_mat,3)>0.40)):

            add_peaks.append(i)
            if bits[i]/nrow_y_mat < 0.01 and bits[i-1]/nrow_y_mat > 0.15:
                add_peaks.append(i-1)

            if bits[i]/nrow_y_mat < 0.01 and bits[i+1]/nrow_y_mat > 0.15:
                add_peaks.append(i+1)




    init_list = np.unique(np.sort(add_peaks))
    temp_list = []
    fin_list_temp = []
    fin_list_sd_temp = []
    search_left_peak = []
    search_right_peak = []
    fin_list = []
    l = []
    j = 1

    for i in np.arange(len(init_list)) :


        if i > 0:
            win = np.arange(-width, width+1)

            if init_list[i] in (init_list[i-1] + win):
                temp_list.append(np.array([init_list[i],init_list[i-1]]))

                if i==len(init_list)-1: #pour le dernier

                    fin_list_temp.append(int(np.round(int(np.mean(np.unique(temp_list))))))
                    fin_list_sd_temp.append((np.max(np.abs(np.median(temp_list)-temp_list))))
                    search_left_peak.append(int(np.round(np.median(temp_list))-np.min(temp_list)))
                    search_right_peak.append(int(np.abs(np.ceil(np.median(temp_list))-np.max(temp_list))))

                    l.append(np.sort(np.unique(temp_list)))
                    j=j+1

            else:

                if((len(temp_list))==0):
                    temp_list=init_list[i-1]

                    fin_list_temp.append(int(init_list[i-1]))
                    fin_list_sd_temp.append((0.0))
                    search_left_peak.append(int(np.round(np.median(temp_list),0)-np.min(temp_list)))
                    search_right_peak.append(int(np.abs(np.ceil(np.median(temp_list))-np.max(temp_list))))
                    l.append(np.sort(np.unique(temp_list)))
                    j=j+1
                    temp_list = []

                else:
                    fin_list_temp.append(int(np.round(int(np.mean(np.unique(temp_list))))))
                    fin_list_sd_temp.append((np.max(np.abs(np.median(temp_list)-temp_list))))
                    search_left_peak.append(int(np.round(np.median(temp_list),0)-np.min(temp_list)))

                    search_right_peak.append(int(np.abs(np.round(np.median(temp_list))-np.max(temp_list))))
                    l.append(np.sort(np.unique(temp_list)))
                    j=j+1
                    temp_list = []


    fin_list.append(init_list[i])
    return fin_list_temp, search_left_peak, search_right_peak, fin_list_sd_temp

#@ray.remote
def fitpeak_sd(spectra_x, spectra_y,peak_list,p_peak):
    peak_list_fin = peak_list[0]
    wvn =peak_list_fin[p_peak]
    search_l_peak_max = peak_list[1][p_peak]
    search_r_peak_max = peak_list[2][p_peak]
    search_peak_l = np.zeros(search_l_peak_max+1) #+1 a cause du 0 on veut un vecteur de longueur 7+1
    search_peak_r = np.zeros(search_r_peak_max+1)
    search_peak_l[0:(search_l_peak_max+1)]=np.arange(0,search_l_peak_max+1,1,dtype=int)
    search_peak_r[0:(search_r_peak_max+1)]=np.arange(0,search_r_peak_max+1,1)
    search_peak_l=search_peak_l.astype(int)
    search_peak_r=search_peak_r.astype(int)
    offset=0
    init_height=0

    sd_peak=0
    app_ind = np.argmin(abs(spectra_x - wvn)) #wvn est la valeur de chaque pic en cm-1, ex: 1448, 722. Donc app_ind contient l'indice de ce pic
    i=0
    peak_found=-99
    peak_ind=[]
    max_length=np.max([len(search_peak_l),len(search_peak_r)])
    local_maxima=[]
    #print("START")
    for i in np.arange(max_length) :
        if peak_found==-99:

            if i < len(search_peak_l):
                j=i
            else: j=0
            if i < len(search_peak_r):
                k=i
            else: k=0

            if search_peak_l[j]==0:
                search_r = np.array([spectra_y[app_ind]])
            else:
                search_r = np.array(spectra_y[(app_ind - search_peak_l[j]) : (app_ind + search_peak_r[k]+1)])
                local_maxima = np.array(np.where(np.diff(np.sign(np.diff(search_r)))==-2)[0])
            if(len(local_maxima) != 0):
                peak_ind = app_ind -search_peak_l[j] + local_maxima[np.argmax(search_r[local_maxima])] +1
                peak_found=peak_ind-app_ind
                init_height=spectra_y[app_ind]
            else :
                peak_ind = app_ind
                peak_found=-99
                init_height=spectra_y[app_ind]

    left=0
    right=0
    r=1
    l=1
    while(left+right<2):
        if peak_ind+r<len(spectra_x) and spectra_y[peak_ind+r-1]>=spectra_y[peak_ind+r]: r=r+1
        else:
            if peak_ind+r+1<len(spectra_x) and spectra_y[peak_ind+r-1]>=spectra_y[peak_ind+r+1]:r=r+2
            else: right=1

        if (peak_ind-l-1>0):
            if(peak_ind-l>0 and spectra_y[peak_ind-l+1]>=spectra_y[peak_ind-l]):l=l+1
            else:
                if (peak_ind-l-1>0 and spectra_y[peak_ind-l+1]>=spectra_y[peak_ind-l-1]):l=l+2
                else: left=1
        else:
            left=1
    search_r_recenter_left_temp = (spectra_y[(peak_ind - l) : peak_ind+1])
    search_r_recenter_left = search_r_recenter_left_temp[::-1]
    search_r_recenter_right = spectra_y[(peak_ind-1): (peak_ind + r+2)]

    infl_r = np.where(np.diff(np.sign(np.diff((search_r_recenter_right))))==2)[0]+2

    if np.all(np.isnan(infl_r)): infl_r = np.where(search_r_recenter_right==0)[0]
    if len(infl_r)==0 :infl_r=np.array([1])
    infl_r_ind = peak_ind + infl_r[0]
    infl_l = np.where(np.diff(np.sign(np.diff((search_r_recenter_left))))==2)[0]+2

    if np.all(np.isnan(infl_l)): infl_l=np.where(search_r_recenter_left==0)[0]
    if len(infl_l)==0 : infl_l=np.array([1])

    infl_l_ind = peak_ind - infl_l[0]
    #print(infl_l_ind, infl_r_ind)

    if peak_ind + r==len(spectra_x) : infl_r_ind=len(spectra_x)
    if peak_ind-l==0 : infl_l_ind=0
    if (infl_r_ind) != 0 and (infl_l_ind) != 0:

        x = spectra_x[infl_l_ind-1 : infl_r_ind+1]
        y = spectra_y[infl_l_ind-1 : infl_r_ind+1]

    if infl_r_ind == 0 or infl_l_ind == 0:
        x = spectra_x[(peak_ind - 3) : (peak_ind + 3)]
        y = spectra_y[(peak_ind - 3) : (peak_ind + 3)]


    # Set initial values for MLE estimation
    m_0 = x[np.argmax(y)]
    s_0 = np.sqrt(np.abs(np.sum(y * (x - m_0)**2) / np.sum(y)))
    if np.isnan(s_0): s_0 = 0
    a_0 = np.max(y)
    return [[a_0, m_0, s_0]]
#    try:
#        popt,pcov=curve_fit(pdf_gaus,x,y,p0=[a_0,m_0,s_0])
#        return [[popt[0], popt[1], popt[2]]]#, peak_found, init_height]]
#    except RuntimeError:
#        return [[a_0, m_0, s_0]]#, peak_found, init_height]]


def pdf_gaus(x,a,x0,sigma):
    return a*np.exp(-(x-x0)**2/(2*sigma**2))

def gausfit(xaxis,spectra, width=5, prom=None, hei=None):
    
    x_mat = xaxis
    y_mat = spectra
    nrow_y_mat=y_mat.shape[0]

    peak_list_fin = get_kpeaks(x_mat, y_mat, width, prom, hei)
    dt = np.zeros((nrow_y_mat, 3 * len(peak_list_fin[0])))
    df_all = pd.DataFrame()
    if y_mat.ndim == 1:
        df = pd.DataFrame()
        for p in np.arange(len(peak_list_fin[0])):
            #fit_params = ray.get(fitpeak_sd.remote(x_mat, y_, peak_list_fin, p))
            fit_params = fitpeak_sd(x_mat, y_mat, peak_list_fin, p)
            df_temp = pd.DataFrame(fit_params, columns=['HEI_'+str(peak_list_fin[0][p]), 'POS_'+str(peak_list_fin[0][p]), 'STD_'+str(peak_list_fin[0][p])])
            df = pd.concat([df, df_temp], axis=1)
        df_all = pd.concat([df_all,df],axis=0)
    else:
        for y_ in y_mat:
            col=0
            df = pd.DataFrame()
            for p in np.arange(len(peak_list_fin[0])):
                #fit_params = ray.get(fitpeak_sd.remote(x_mat, y_, peak_list_fin, p))
                fit_params = fitpeak_sd(x_mat, y_, peak_list_fin, p)
                df_temp = pd.DataFrame(fit_params, columns=['HEI_'+str(peak_list_fin[0][p]), 'POS_'+str(peak_list_fin[0][p]), 'STD_'+str(peak_list_fin[0][p])])
                df = pd.concat([df, df_temp], axis=1)
            df_all = pd.concat([df_all,df],axis=0)
    return df_all, peak_list_fin

class FeatureReduction:
    def __init__(self):
        pass
    def fit(self, X, y=None, xaxis=None, feature_set=None):
        """
        Find the index positions of a feature set in xaxis

        Parameters
        ----------
        X: array-like of shape (n_samples, n_features)
            Data that needs to be feature reduced

        xaxis: array-like of shape (n_features,), default=None
            Wavenumbers in cm-1

        feature_set: array-like of size < n_features, default=None
            Subset of wavenumbers in cm-1

        y: None
            Ignored

        Returns
        -------
        self: object
            Fitted estimator
        """
        
        self.n_features_ = X.shape[1]
        if xaxis.ndim > 1:
            raise IndexError("`xaxis` must be one dimensional")
        if feature_set.ndim > 1:
            raise IndexError("`feature_set` must be one dimensional")
        if feature_set.size > xaxis.size:
            raise IndexError("`features` must have a length smaller or equal to `xaxis`")
        if xaxis.size != self.n_features_:
            raise ValueError("`xaxis` shape {} must match with `n_features` ({},)".format(xaxis.shape, self.n_features_))
        #self.list_args_ = np.where(feature_set[:, None] == xaxis)[1]
        self.list_args_ = np.where(np.isin(xaxis, feature_set))[0]
    def transform(self, X, copy=None):
        """
        Reduced X to the subset of features

        Parameters
        ----------
        X: array of shape (n_samples, n_features)
            Input samples

        Returns
        -------
        X_r: array of shape (n_samples, n_reduced_features)
            Input samples with only the subset of reduced features            
        """
        if X.shape[1] != self.n_features_:
            raise ValueError("Number of features in `X` ({},) does not match initial number of features ({},)".format(X.shape[1], self.n_features_))
        return X[:, self.list_args_]

class SpectralAngleMapper:
    '''
    Spectral angle mapping calculations between an input signal
    and a reference spectrum. Multiple references can be entered
    in the form of a pandas DataFrame or as a single entry in numpy
    array format.
    '''
    def __init__(self, reference=None):
        '''
        Parameters
        ----------

        reference: pandas DataFrame of shape (n_reference, 3), default=None
            If 'None', standalone mode with no reference to be compared with
            Otherwise reference must contain the following keys:
                - name: str
                - average_spectrum: ndarray of shape (n_features,)
                - sam_mean: float
                - sam_std: float
        '''
        if reference is None:
            self.reference = reference
        else:
            if self.reference_is_valid(reference):
                self.reference = reference

    def reference_is_valid(self, reference):
        if reference.empty:
            raise IndexError("'DataFrame' is empty")
            
        for k in ['name', 'average_spectrum', 'sam_mean', 'sam_std']:
            if k not in reference.keys():
                raise AttributeError("'DataFrame' object has no attribute '{}'".format(k))
        
        return True
        
    def calculate_angle(self, signal=np.ndarray, reference_name=None, reference_spectrum=None):
        '''
        This function calculates the SAM value between an input signal and a reference
        spectrum, either provided in the constructor or as input to this method.

        Parameters
        ----------
        signal: ndarray of shape (n_features,)

        reference_name: str, default=None
            If None, a reference spectrum must be provided to reference_spectrum. The combination `reference_name=None` and `reference_spectrum=None` is not supported.
            If str, `reference_spectrum` must be set to None

        reference_spectrum: ndarray of shape (n_features,), default=None
            If None, a valid entry must be provided in `reference_name`
            If ndarray, `reference_name` must be set to None

        Returns
        -------
        float
            SAM value in radians
        '''
        
        if reference_name is None and reference_spectrum is None:
            raise ValueError("Unsupported set of arguments: The combination `reference_name=None` and `reference_spectrum=None` is not supported")
            
        if reference_name is not None and reference_spectrum is not None:
            raise ValueError("Unsupported set of arguments: The combination where `reference_name` and `reference_spectrum` are both initialized creates a conflict. Set either one to None.")
        
        if reference_spectrum is not None:
            ref = reference_spectrum
            
        if reference_name is not None:
            if self.reference is None:
                raise AttributeError("object was instantiated with a reference=None")
            if reference_name not in self.reference.name.unique():
                raise ValueError("'{}' is not included in 'name'".format(reference_name))
            ref = self.reference[self.reference.name==reference_name].iloc[0].average_spectrum

        # Calculate SAM between ref and signal
        rs = np.sum(ref*signal)
        norm_r = np.sqrt(np.sum(ref*ref))
        norm_s = np.sqrt(np.sum(signal*signal))

        #try:
        #    return float(np.rad2deg(math.acos(rs/(norm_r * norm_s))))
        #except ValueError:
        #    return float(np.rad2deg(math.acos(rs/(norm_r * norm_s)+1-1)))
        return float(rs/(norm_r * norm_s))

    def angle_in_degrees(self, sam_value):
        '''
        This function calculates the SAM value between an input signal and a reference
        spectrum, either provided in the constructor or as input to this method.

        Parameters
        ----------
        signal: ndarray of shape (n_features,)

        reference_name: str, default=None
            If None, a reference spectrum must be provided to reference_spectrum. The combination `reference_name=None` and `reference_spectrum=None` is not supported.
            If str, `reference_spectrum` must be set to None

        reference_spectrum: ndarray of shape (n_features,), default=None
            If None, a valid entry must be provided in `reference_name`
            If ndarray, `reference_name` must be set to None

        Returns
        -------
        float
            SAM value in  degrees
        '''
        try:
            return float(np.rad2deg(math.acos(sam_value)))
        except ValueError:
            return float(np.rad2deg(math.acos(sam_value+1-1)))
        
    def calculate_nb_standard_dev(self, sam_value=float, reference_name=None, sam_refs=None):
        '''
        This function returns within how many standard deviations the input
        value is (minimum value being 1 st. dev.) from a given reference.

        Parameters
        ----------
        sam_value: float
            SAM value calculated, to be compared with a reference value

        reference_name: str, default=None
            If None, reference values must be provided to sam_refs. The combination `reference_name=None` and `sam_refs=None` is not supported.
            If str, sam_refs must be set to None

        sam_refs: array-like of shape (2,), default=None
            If None, a valid entry must be provided in reference_name
            Otherwise, `reference_name` must be set to None

        Returns
        -------
        int
            Number of standard deviations
        '''
        
        if reference_name is None and sam_refs is None:
            raise ValueError("Unsupported set of arguments: The combination `reference_name=None` and `sam_refs=None` is not supported")
            
        if reference_name is not None and sam_refs is not None:
            raise ValueError("Unsupported set of arguments: The combination where `reference_name` and `sam_refs` are both initialized creates a conflict. Set either one to None.")

        if sam_refs is not None:
            for k in ['mean', 'std']:
                if k not in sam_refs.keys():
                    raise KeyError("'dict' object has no key '{}'".format(k))
            sam_mean = sam_refs['mean']
            sam_std  = sam_refs['std']

        if reference_name is not None:
            if self.reference is None:
                raise AttributeError("object was instantiated with a reference=None")
            if reference_name not in self.reference.name.unique():
                raise ValueError("'{}' is not included in 'name'".format(reference_name))
        
            sam_mean = self.reference[self.reference.name==reference_name].iloc[0].sam_mean
            sam_std  = self.reference[self.reference.name==reference_name].iloc[0].sam_std
        
        return int((sam_value-sam_mean)/sam_std)+1

# Class for cross validation with extensive output parameters
class CrossValidator:
    '''
    Create instances containing the input parameters and output results
    to asses model performances through cross validation. Input  parameters
    are necessary to initialise the feature selection and classification algorithms.
    '''
    
    def __init__(self, **kwargs):
        self.params = kwargs
        self.variables_ = {}
    
    #def set_params(self, k, v):
    #    self.params[k] = v
    
    def get_params(self, k):
        return self.params.get(k, None)
    
    def set_variable(self, k, v):
        self.variables_[k] = v
    
    def get_variable(self, k):
        return self.variables_.get(k, None)

    def training(self, xaxis=np.ndarray, features=dict, y=np.ndarray, groups=np.ndarray, splitter=sklearn.model_selection.BaseCrossValidator, extra_dict=None, scaling=True):
        '''
        Trains an input model via cross validation
            
        Parameters
        ----------
        xaxis: ndarray of shape (n_features,)
            Wavenumbers in cm-1
            
        features: dict
            - key 'raman' is mandatory.
                - raman: ndarray of shape (n_samples, n_features)
            - any extra key will be concatenated to the raman features 
            set after feeature selection.
                - extra features: ndarray of shape (n_samples,)
                             
        y: ndarray of shape (n_samples,)
            Class label for each sample.
                             
        groups: ndarray of shape (n_samples,)
            Individual groups among all samples, necessary for GroupKFold().
                             
        splitter: sklearn.model_selection.BaseCrossValidator
            CV splitter instance (GroupKFold(), StratifiedKFold(), etc.) already initialized with n_splits.
                             
        extra_dict: dict, default=None
            Each key is ndarray of shape (n_samples,). For investigation purposes,
            each key element will be split according to the cross validation folds.

        scaling: bool, default=True
            If True, calls StandardScaler() before feature selection
            
        Attributes
        ----------
            
        variables_: dict
            Relevant informations related to the cross validation performed: feature
            selection and classification parameters, classification results
                             
            Classification results: 
                auc: float
                    area under the curve, for two-class models only
                accuracy: float
                    classification accuracy, provided for models with at least three classes
                fpr: ndarray
                    false positive rate
                tpr: ndarray
                    true positive rate
                thl: ndarray
                    ROC curve thresholds
                labels: ndarray of shape (n_samples,)
                    class labels for each sample
                preds: ndarray of shape (n_samples,)
                    classification predictions for each sample
                probs: ndarray of shape (n_samples,)
                    classification probabilities for each sample
                index: ndarray of shape (n_samples,)
                    sample indexes used in each fold
                samples: array-like of shape (n_folds)
                    sample ID (groups) used in each fold
                nb_feats: array-like of shape (n_folds)
                    number of features used in each fold
                feats: array-like of shape (n_folds)
                    features in cm-1 used in each fold
                train_set: array-like of shape (n_folds, n_classes)
                    number of training samples of each class used in each fold
                valid_set: array-like of shape (n_folds, n_classes)
                    number of validation samples of each class used in each fold
                nb_sv: array-like of shape (n_folds, n_classes)
                    number of support vector for each fold, only for SVM classification algorithm
                             
        '''
        self.xaxis = xaxis
        self.features = features
        self.y = y
        self.groups = groups
        if not issubclass(type(splitter), sklearn.model_selection.BaseCrossValidator):
            raise TypeError("`splitter` must be a sklearn.model_selection.BaseCrossValidator inherited class, such as StratifiedKFold, GroupKFold, etc.")
        self.splitter = splitter
        if len(self.get_params('max_features')) > 1:
            self.max_features = [s for s in self.get_params('max_features')]
        else:
            self.max_features = self.get_params('max_features')
        self.extra_dict = extra_dict
        self.scaling = scaling

        self.parameter_attributes()
        self.cross_validation()
        self.result_attributes()
    
    def cross_validation(self):
        '''
        Runs the cross validation loop over pre-defined number of folds
        '''
        if 'raman' not in self.features.keys():
            raise KeyError("'dict' object has no key 'raman'")
        self.X = self.features['raman']
        if 'peaks' in self.features.keys():
            self.P = self.features['peaks']
        
        # Initiliaze empty lists
        self.labels, self.probs, self.preds  = [],[],[]
        self.samples, self.feats = [],[]
        self.train_labels, self.valid_labels = [],[]
        self.nb_feats , self.nb_sv = [],[]
        self.valid_indexes = []
        
        for train_idx, valid_idx in self.splitter.split(self.X, self.y, groups=self.groups):
            train_X = self.X[train_idx]
            valid_X = self.X[valid_idx]
            train_y = self.y[train_idx]
            valid_y = self.y[valid_idx]
            valid_groups = self.groups[valid_idx]
            self.valid_indexes.append(valid_idx)
            if 'peaks' in self.features.keys():
                train_P = self.P[train_idx]
                valid_P = self.P[valid_idx]

            if self.scaling:
                scaler = StandardScaler().fit(train_X)
                trans_train_X = scaler.transform(train_X)
                trans_valid_X = scaler.transform(valid_X)
            else:
                trans_train_X = train_X
                trans_valid_X = valid_X
            
            sfm = SelectFromModel(self.fs[0].set_params(**self.fs_params[0]),
                                  max_features=self.max_features[0]).fit(trans_train_X, train_y)
            feat_idx = self.xaxis[sfm.get_support(indices=True)]
            best_train_X = sfm.transform(trans_train_X)
            best_valid_X = sfm.transform(trans_valid_X)
            
            if 'peaks' in self.features.keys():
                sfm = SelectFromModel(self.fs[1].set_params(**self.fs_params[1]),
                                      max_features=self.max_features[1]).fit(train_P, train_y)
                best_train_P = sfm.transform(train_P)
                best_valid_P = sfm.transform(valid_P)
                best_train_X = np.concatenate((best_train_X,best_train_P), axis=1)
                best_valid_X = np.concatenate((best_valid_X,best_valid_P), axis=1)
            
            list_keys = [c for c in self.features.keys() if c not in ['raman', 'peaks']]
            if len(list_keys):
                train_extra = np.concatenate([v[train_idx] for k,v in self.features.items() if k not in ['raman', 'peaks']], axis=1)
                valid_extra = np.concatenate([v[valid_idx] for k,v in self.features.items() if k not in ['raman', 'peaks']], axis=1)
                best_train_X = np.concatenate((best_train_X, train_extra), axis=1)
                best_valid_X = np.concatenate((best_valid_X, valid_extra), axis=1)
            model_cv = self.clf.set_params(**self.clf_params)
            model_cv = model_cv.fit(best_train_X, train_y)
            
            self.labels.append(valid_y)
            self.preds.append(model_cv.predict(best_valid_X))
            self.probs.append(model_cv.predict_proba(best_valid_X))#[:,1])
            self.samples.append(valid_groups)
            self.feats.append(feat_idx)
            self.nb_feats.append(feat_idx.size)
            self.train_labels.append([np.where(train_y==i)[0].size for i in np.sort(np.unique(train_y))])
            self.valid_labels.append([np.where(valid_y==i)[0].size for i in np.sort(np.unique(valid_y))])
            if self.get_params('clf_algo').__class__.__name__ == 'SVC':
                self.nb_sv.append(model_cv.n_support_)
        
        #self.preds   = np.array(self.preds).ravel()
        #self.probs   = np.array(self.probs).ravel()
        #self.labels  = np.array(self.labels).ravel()
        #self.samples = np.array(self.samples).ravel()
        #self.valid_indexes = np.array(self.valid_indexes).ravel()
        self.preds   = np.array([p for pp in self.preds for p in pp])
        self.probs   = np.array([p for pp in self.probs for p in pp])
        self.labels  = np.array([p for pp in self.labels for p in pp])
        self.samples = np.array([p for pp in self.samples for p in pp])
        self.valid_indexes = np.array([p for pp in self.valid_indexes for p in pp])

    def parameter_attributes(self):
        # Feature selection algo
        self.fs_algo_name = [s.__class__.__name__ for s in self.get_params('fs_algo')]
        # Classifier algo
        self.clf_algo_name = self.get_params('clf_algo').__class__.__name__
        
        algos = np.r_[[s for s in self.fs_algo_name], [self.clf_algo_name]]
        self.set_variable('algo','/'.join(algos))

        # Feature selection algorithms
        self.fs = [s for s in self.get_params('fs_algo')]
        self.fs_params = [p for p in self.get_params('fs_params')]

        # Classification algorithm
        self.clf = self.get_params('clf_algo')
        self.clf_params = self.get_params('clf_params')

        # Feature selection parameters
        for i in range(len(self.fs_algo_name)):
            if self.fs_algo_name[i] == 'LinearSVC':
                #self.set_variable('fs_C', self.fs_params[i]['C'])
                self.set_variable('fs_C', self.get_params('fs_params')[i]['C'])
            elif self.fs_algo_name[i] == 'RandomForestClassifier':
                self.set_variable('nb_estimators', self.fs_params[i]['n_estimators'])
        if len(self.max_features) > 1:
            for i in range(len(self.max_features)):
                if self.max_features != None:
                    self.set_variable('max_feats_'+str(i), self.max_features[i])
        else:
            self.set_variable('max_feats', self.max_features[0])

        # Classification algorithm parameters
        if self.clf_algo_name == 'SVC':
            self.set_variable('clf_C', self.clf_params['C'])
            self.set_variable('clw', self.clf_params['class_weight'])
        elif self.clf_algo_name == 'XGBClassifier':
            for k,v in clf_params.items():
                self.set_variable(k, v)

    def result_attributes(self):
        # Model main performance, AUC (2 classes) or accuracy (3+ classes)
        if np.unique(self.y).size == 2:
            fpr, tpr, thl = roc_curve(self.labels, self.probs[:, 1])
            self.set_variable('auc', auc(fpr, tpr))
        else:
            cm = confusion_matrix(self.labels, self.preds)
            self.set_variable('accuracy', np.trace(cm)/np.sum(cm))
            
        # ROC curve data
        if np.unique(self.y).size == 2:
            self.set_variable('fpr', fpr)
            self.set_variable('tpr', tpr)
            self.set_variable('thl', thl)

        # Training labels
        self.set_variable('labels', self.labels)
        
        # Training probabilities and predictions
        if np.unique(self.y).size == 2:
            self.set_variable('probs', self.probs)
        else:
            self.set_variable('probs', self.probs)
            self.set_variable('preds', self.preds)

        # Info related to folds
        self.set_variable('samples',   self.samples)
        self.set_variable('nb_feats',  self.nb_feats)
        self.set_variable('feats',     self.feats)
        self.set_variable('train_set', self.train_labels)
        self.set_variable('valid_set', self.valid_labels)

        # Number of support vectors per fold for SVM
        if self.clf_algo_name == 'SVC':
            self.set_variable('nb_sv', self.nb_sv)
        if self.extra_dict!=None:
            for k in self.extra_dict.keys():
                tmp = [self.extra_dict[k][ii] for ii in self.valid_indexes]
                tmp = np.array([t for tt in tmp for t in tt])
                self.set_variable(k, tmp)