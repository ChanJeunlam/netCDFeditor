#tifedit.py
import os
import sys
import glob
import pandas as pd
from osgeo import gdal

drv = gdal.GetDriverByName("GTiff")

def getbands(geotiff, verbose = False):
    print("~ Processing: "+geotiff)
    raster = gdal.Open(geotiff)
    bands = []

    for bandnumber in range(1, raster.RasterCount+1):
        band = raster.GetRasterBand(bandnumber)
        bands.append([
            geotiff,
            bandnumber,
            band.GetDescription(),
            str(band.GetMetadata())])
            
    df = pd.DataFrame(bands, 
        columns=["GeoTIFF","Band","Description", "Metadata"])

    return(df)

def writegeotiff(geotiff=None, bands=None, tail="_edit.tif"):

    # duplicate input dataset and open;  
    outraster = drv.CreateCopy(
        os.path.splitext(geotiff)[0]+tail,  # output geotiff
        gdal.Open(geotiff))                 # input gdal raster dataset   

    # iterate over bands; write info from table
    for bandnumber in range(1, outraster.RasterCount+1):

        try:
            bandrow = bands.loc[bands["Band"]==bandnumber]
            band = outraster.GetRasterBand(bandnumber)
            band.WriteArray(band.ReadAsArray())
            band.SetDescription(bandrow['Description'].item())
            band.SetMetadata(bandrow['Metadata'].item())

        except:
            print("No row found for band "+str(bandnumber)+". Skipping.")

    outraster.FlushCache()
    outraster = None # close file

if __name__ == '__main__':

    if len(sys.argv) is not 2:
        sys.exit("ERROR: tifedit.py requires 1 argument. Exiting.")

    elif os.path.isdir(sys.argv[1]):
        print("Got input path. Writing GeoTIFF bands table.")
        tifs = glob.glob(sys.argv[1]+"/*.tif")
        df = pd.concat([getbands(t) for t in tifs])
        df.to_csv("bands.csv")

    elif os.path.isfile(sys.argv[1]):
        print("Got input file. Writing new GeoTIFFs from CSV info.")
        bands = pd.read_csv(sys.argv[1])
        for geotiff in bands.GeoTIFF.unique():
            bands = bands.loc[bands["GeoTIFF"]==geotiff]
            writegeotiff(geotiff=geotiff, bands=bands)

    else:
        print("Something went wrong. Exiting.")