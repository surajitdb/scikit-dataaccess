import pandas as pd
import numpy as np
from itertools import combinations
from netCDF4 import Dataset, num2date
from collections import OrderedDict


def averageDates(dates, round_nearest_day = False):
    '''
    Compute the average of a pandas series of timestamps

    @param dates: Pandas series of pandas datetime objects
    @param round_nearest_day: Round to the nearest day

    @return Average of dates
    '''
    start = dates.min()
    newdate = (dates - start).mean() + start
    if round_nearest_day:
        newdate = newdate.round('D')
    return newdate


def dateMismatch(dates, days=10):
    '''
    Check if dates are not within a certain number of days of each other

    @param dates: Iterable container of pandas timestamps
    @param days: Number of days

    @return true if they are not with 10 days, false otherwise
    '''
    for combo in combinations(dates,2):
        if np.abs(combo[0] - combo[1]) > pd.to_timedelta(days, 'D'):
            return True
    return False

def computeEWD(grace_data, scale_factor, round_nearest_day=False):
    '''
    Compute scale corrected equivalent water depth

    Equivalent water depth by averaging results from
    GFZ, CSR, and JPL, and then applying the scale factor

    @param grace_data: Data frame containing grace data
    @param scale_factor: Scale factor to apply
    @param round_nearest_day: Round dates to nearest day

    @return Equivalent water depth determined by applying the scale factor to
            the average GFZ, JPL and CSR.
    '''
    
    def cutMissingData(in_data, reverse=False):
        '''
        Removes data from the beginning (or ending if reverse=True) so that
        data exists for all 3 sources (GFZ, JPL, and CSR). 


        This function is necessary as not all sources may get cut when
        a starting and ending date is specified.

        @param in_data: Input grace data
        @param reverse: Remove data from end instead of beginning
        
        @return Tuple containing modified in_data, the last cut date
        '''

        last_cut_date = None

        if reverse==True:
            index = in_data.index[::-1]
        else:
            index = in_data.index

        for date in index:
            cut = in_data.loc[date-pd.to_timedelta('10D'):date+pd.to_timedelta('10D')]
            if min(len(cut['CSR'].dropna()), len(cut['GFZ'].dropna()), len(cut['JPL'].dropna())) == 0:
                if reverse:
                    in_data = in_data.iloc[:-1]
                else:
                    in_data = in_data.iloc[1:]

                last_cut_date = date
                
            else:
                break

        return in_data,last_cut_date

    # Check if there is no valid data
    if len(grace_data['CSR'].dropna()) + len(grace_data['GFZ'].dropna()) + len(grace_data['JPL'].dropna()) == 0:
        if round_nearest_day == True:
            return pd.Series(np.nan, index=grace_data.index.round('D'))
        else:
            return pd.Series(np.nan, index=grace_data.index)
    
    # Find all months that have different dates supplied by GFZ, JPL, and CSR
    offsets = grace_data[grace_data.isnull().any(axis=1)]

    # Starting and ending months if they don't have valid data for all 3 data sets
    offsets,cut_date1 = cutMissingData(offsets)
    offsets,cut_date2 = cutMissingData(offsets, reverse=True)

    # If beginning data has been cut, update data accordingly
    if cut_date1 != None:
        index_location = np.argwhere(grace_data.index == cut_date1)[0][0]
        new_index = grace_data.index[index_location+1]
        grace_data = grace_data.loc[new_index:]

    # If ending data has been cut, update data accordingly
    if cut_date2 != None:
        index_location = np.argwhere(grace_data.index == cut_date2)[0][0]
        new_index = grace_data.index[index_location-1]
        grace_data = grace_data.loc[:new_index]


    # Get all valid data for JPL, GFZ, and CSR
    csr = offsets['CSR'].dropna()
    gfz = offsets['GFZ'].dropna()
    jpl = offsets['JPL'].dropna()


    new_index = []
    new_measurements = []
    
    # Iterate over all data with offset dates and combine them
    for (c_i, c_v), (g_i,g_v), (j_i, j_v) in zip(csr.iteritems(), gfz.iteritems(), jpl.iteritems()):

        # Check if the dates are within 10 days of each other
        dates = pd.Series([c_i,g_i,j_i])
        if dateMismatch(dates):
            raise ValueError('Different dates are not within 10 days of each other')

        # Determine new index and average value of data  
        new_index.append(averageDates(dates, round_nearest_day))
        new_measurements.append(np.mean([c_v, g_v, j_v])) 

    # Create series from averaged results
    fixed_means = pd.Series(data = new_measurements, index=new_index)
    fixed_means.index.name = 'Date'

    # Averaging results from non mimsatched days
    ewt = grace_data.dropna().mean(axis=1)

    # If requested, round dates to nearest day
    if round_nearest_day:
        ewt_index = ewt.index.round('D')
    else:
        ewt_index = ewt.index

    # Reset ewt index
    ewt = pd.Series(ewt.as_matrix(),index = ewt_index)

    # Combined data with mismatched days with data
    # without mismatched days
    ewt = pd.concat([ewt, fixed_means])
    ewt.sort_index(inplace=True)

    # Apply scale factor
    ewt = ewt * scale_factor

    # Return results
    return ewt


def readTellusData(filename, lat_lon_list, lat_name, lon_name, data_name, time_name=None,
                   lat_bounds_name=None, lon_bounds_name=None, uncertainty_name = None):
    ''' 
    This function reads in netcdf data provided by GRACE Tellus

    @param filename: Name of file to read in
    @param lat_name: Name of latitude data
    @param lon_name: Name of longitude data
    @param data_name: Name of data product
    @param time_name: Name of time data
    @param lat_bounds_name: Name of latitude boundaries
    @param lon_bounds_name: Name of longitude boundaries
    '''


    def findBin(in_value, in_bounds):
        search = np.logical_and(in_value >= in_bounds[:,0], in_value < in_bounds[:,1])

        if np.sum(search) == 1:
            return np.argmax(serach)
        elif in_value == in_bounds[-1]:
            return len(in_bounds)-1
        else:
            raise RuntimeError("Value not found")

    nc = Dataset(filename, 'r')

    lat_data = nc[lat_name][:]
    lon_data = nc[lon_name][:]
    data = nc[data_name][:]

    if lat_bounds == None and lon_bounds == None:
        time = nc.variables[time]

        lat_delta = (lat_data[1] - lat_data[0])/2
        lon_delta = (lon_data[1] - lon_data[0])/2

        lat_bounds = np.stack([lat_data-lat_delta, lat_data+lat_delta]).T
        lon_bounds = np.stack([lon-lon_delta, lon+lon_delta]).T
        
    else:
        lat_bounds = nc[lat_bounds_name][:]
        lon_bounds = nc[lon_bounds_name][:]

    if time_name != None:
        time = nc[time_name][:]
        date_index = pd.to_datetime(num2date(time[:],units=time.units,calendar=time.calendar))

    return_data = OrderedDict()


    if uncertainty_name != None:
        uncertainty = nc[uncertainty_name][:]

    for lat, lon in lat_lon_list:

        # Convert lontitude to 0-360
        if lon < 0:
            lon += 360.

        
        lat_bin = findBin(lat, lat_bounds)
        lon_bin = findBin(lon, lon_bounds)

        if time_name != None and uncertainty_name != None:
            pd.DataFrame([data, uncertainty], columns=[
        

    # return_data = OrderedDict()
    # return_data['data'] = data
    # return_data['lat'] = lat
    # return_data['lon'] = lon
    # return_data['lat_bounds'] = lat_bounds
    # return_data['lon_bounds'] = lon_bounds
    # return_data['data_index'] = date_index


    

    return return_data
