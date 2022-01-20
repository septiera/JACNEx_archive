#!/usr/bin/env python3
# coding: utf-8

#############################################################################################################
###################################### STEP3 VCF Formatting #################################################
#############################################################################################################
# How the script works ?
#This script allows to format the results of CNV calls obtained with Bedtools/ExomeDepth in VCF.
#Several steps are required for this formatting:
#-checking the format of the input file.
#-Pre-processing of the data (removal of padding, filtering on the BF, obtaining the copy number column)
#-Definition of a hash table allowing an optimal data processing (key=chromosome:start_end; value=sample_CN_BayesFactor_ReadsRatio)
#-Formatting
#-Addition of the vcf header and saving.

#The input parameters:
#-the path to the .tsv file of the ExomeDepth output.
#-the path to save the output vcf.
#-Bayes factor filtering threshold (all CNVs with a lower BF level will be removed from the analysis).

#The output file must respect the vcf v4.3 format. (cf https://samtools.github.io/hts-specs/VCFv4.3.pdf)
#It can then be annotated by the VEP software.

#############################################################################################################
################################ Loading of the modules required for processing #############################
#############################################################################################################

import pandas as pd #is a module that makes it easier to process data in tabular form by formatting them in dataframes as in R.
import numpy as np #is a module often associated with the pandas library it allows the processing of matrix or tabular data.
import os #this module provides a portable way to use operating system-dependent functionality. (opening and saving files)
os.environ['NUMEXPR_NUM_THREADS'] = '10' #allows to define a CPUs minimum number to use for the process. Must be greater than the cores number defined below.
import sys, getopt #this module provides system information. (ex argv argument)
import time #is a module for obtaining the date and time of the system.
import logging #is a practical logging module. (process monitoring and development support)
import re #this module allows you to search and replace characters with regular expressions. (similar to "re" module)

#Scripts execution date definition(allows to annotate the output files to track them over time) 
now=time.strftime("%y%m%d")

#CPU number definition to use during parallelization.
num_cores=5

pd.options.mode.chained_assignment = None

#####################################################################################################
################################ Logging Definition #################################################
#####################################################################################################
#create logger : Loggers expose the interface that the application code uses directly
logger=logging.getLogger(os.path.basename(sys.argv[0]))
logger.setLevel(logging.DEBUG)
#create console handler and set level to debug : The handlers send the log entries (created by the loggers) to the desired destinations.
ch = logging.StreamHandler(sys.stderr)
ch.setLevel(logging.DEBUG)
#create formatter : Formatters specify the structure of the log entry in the final output.
formatter = logging.Formatter('%(asctime)s %(name)s: %(levelname)-8s [%(process)d] %(message)s', '%Y-%m-%d %H:%M:%S')
#add formatter to ch(handler)
ch.setFormatter(formatter)
#add ch(handler) to logger
logger.addHandler(ch)

#####################################################################################################
################################ Functions ##########################################################
#####################################################################################################
####################################################
#Canonical transcripts sanity check.
#This function is useful for the bed file of canonical transcripts.
#It allows to check that the input file is clean.

#Input:
#-the path to the table under test.
# It is divided into several steps:
#-Step I): check that the loaded table contains 4 columns + name addition.
#-Step II): Column content verification
#   -- CHR : must start with "chr" and contain 25 different chromosomes (if less or more return warnings). The column must be in object format for processing.
#   -- START , END : must be in int64 format and not contain null value (necessary for comparison steps after calling CNVs)
#   -- TranscriptID_ExonNumber : all lines must start with ENST and end with an integer for exonNumber. The column must be in object format for processing.

#Output: This function returns a dataframe 

def InputParseAndSanityCheck(PathToResults,outputFile):
    filename=os.path.basename(PathToResults)
    logger.info("Result calling CNV file %s Parsing and Sanity Check:",filename)
    if not os.path.isfile(PathToResults):
        logger.error("Result calling CNV file %s doesn't exist.",filename)
        sys.exit()
    resToCheck=pd.read_table(PathToResults,sep="\t")
    #####################
    #I): check that the loaded table contains 4 columns + columns renaming.
    #####################
    if len(resToCheck.columns) == 15:
        logger.info("%s contains 15 columns as expected.",filename)
        # check that the column names are the expected ones.
        listcolumns=['sample', 'correlation', 'N.comp', 'start.p', 'end.p', 'type', 'nexons','start', 'end', 'chromosome', 'id', 'BF', 'reads.expected','reads.observed', 'reads.ratio']
        if (set(list(resToCheck.columns)))== set(listcolumns):
            logger.info("%s contains the correct column names.", filename)
        
            #######################
            #II) : Sanity Check
            #######################
            #only the columns useful for processing are checked 
            #######################
            #sample column
            if resToCheck["sample"].dtype=="O":
                logger.info("Sample column has a correct format.")   
            else:
                logger.error("Sample column doesn't have an adequate format. Please check it."
                            +"\n The column must constains string.")
                sys.exit()

            #######################
            #type column
            if (set(list(resToCheck["type"].unique()))==set(["duplication","deletion"]))and (resToCheck["type"].dtype=="O"):
                logger.info("Type column contains the expected annotations..")   
            else:
                logger.error("Type column doesn't contains the expected annotations. Please check it."
                            +"\n  The column must constains string")
                sys.exit()

            #######################
            #start and end column
            if (resToCheck["start"].dtype=="int64") and (resToCheck["end"].dtype=="int64"):
                logger.info("Start End columns have a correct format.") 
                resToCheck["Length"]=resToCheck["end"]-resToCheck["start"]
                if (len(resToCheck.loc[resToCheck.Length<0,])>0):
                    logger.warning("Bad calling from ExomeDepth. Intervals of CNVs not conforming in "+resToCheck.loc[resToCheck.Lenght<0,]+"cases."
                            +"\n  Save and delete these bad predictions.")
                    BadCalls=resToCheck.loc[resToCheck.Lenght<0,]
                    BadCalls.to_csv(outputFile+"/BadCalls_"+now+".tsv", sep="\t", index=False)
                    resToCheck=resToCheck.loc[resToCheck.Lenght>0,]
            else:
                logger.error("One or both of the 'start' and 'end' columns are not in the correct format. Please check."
                            +"\n   The columns must contain integers.")
                sys.exit()

            #######################
            #chromosome column
            #format test and suitable chr number
            if (resToCheck["chromosome"].dtype=="O"):
                if len(resToCheck["chromosome"].unique())==25:
                    logger.info("Chromosome column has a correct format.")   
                else:
                    logger.warning("The calling output file does not have results for all chromosomes = %s (Normally 24+chrM).", len(resToCheck["chromosome"].unique()))
            else:
                logger.error("The 'chromosome' column doesn't have an adequate format. Please check it. "
                            +"\n  The column must constains string.")
                sys.exit()
            #reformatting the column if it does not start with "chr"
            if (resToCheck.chromosome.str.startswith('chr')).all():
                logger.info("Chromosome columns data starts with 'chr' no format change.")
            else:
                logger.info("Chromosome columns data doesn't starts with 'chr' format change.")
                resToCheck["chromosome"]="chr"+resToCheck["chromosome"]

            #######################
            #Bayes factor column 
            if resToCheck["BF"].dtype=="float64":
                logger.info("BF column has a correct format.") 
            else:
                logger.error("BF column is not in the correct format. Please check."
                        +"\n  The columns must contain float.")
                sys.exit()

            #######################
            #reads.ratio columns
            if resToCheck["reads.ratio"].dtype=="float64":
                logger.info("Reads ratio column has a correct format.") 
            else:
                logger.error("Read ratio column is not in the correct format. Please check."
                        +"\n   The columns must contain float.")
                sys.exit()
        else:
            logger.error("%s does not contain the expected column names. Please Check."
                        +"\n Expected columns: %s"
                        +"\n Input file columns: %s",filename,listcolumns,list(resToCheck.columns))
            sys.exit()            
    else:
        logger.error("%s does not contain the expected number of columns. (%s/15).Please check.",filename,len(list(resToCheck.columns)))
        sys.exit()

    return(resToCheck)


####################################################
#This function creates a result line in VCF format: "#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", "PatientsCNVStatusFormat"
#Inputs parameters:
#sample= sample name string
#chrom=number or letter corresponding to the chromosome in string format (not preceded by chr)
#pos=cnv start (int)
#key=corresponds to the absolute identifier of the CNV: "CHR:start-end" (string)
#end=cnv end (int)
#CN=copy number (int), BF= Bayes Factor (float), RR= reads ratio (float)
#listS= samples names list
 
def ResultsListInitialisation(sample,chrom,pos,key,end,CN,BF,RR,listS):
    listResults=["0/0"]*len(listS)      
    #the value under analysis comes from a deleted CNV.
    if int(CN)<2: 
        line=[chrom,pos,key,".","<DEL>",".",".","SVTYPE=DEL;END="+end,"GT:BF:RR"]
        if int(CN)==0: # Homo-deletion
            ValueToAdd=("1/1:"+str(round(float(BF),2))+":"+str(round(float(RR),2)))
            indexToKeep=listS.index(sample)
            listResults[indexToKeep]=ValueToAdd
        elif int(CN)==1: #Hetero-deletion
            ValueToAdd=("0/1:"+str(round(float(BF),2))+":"+str(round(float(RR),2)))
            indexToKeep=listS.index(sample)
            listResults[indexToKeep]=ValueToAdd
    #the value under analysis comes from a duplicated CNV.
    elif int(CN)>2:
        line=[chrom,pos,key,".","<DUP>",".",".","SVTYPE=DUP;END="+end,"GT:CN:BF:RR"]
        ValueToAdd=("0/1:"+str(int(CN))+":"+str(round(float(BF),2))+":"+str(round(float(RR),2)))
        indexToKeep=listS.index(sample)
        listResults[indexToKeep]=ValueToAdd  

    line=line+listResults
    return(line)

#This function allows to complete the lines already generated by the previous function.
#Format: "#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", "PatientsCNVStatusFormat"
#Inputs parameters:
#sample= sample name string
#CN=copy number (int), BF= Bayes Factor (float), RR= reads ratio (float)
#listS= samples names list
#line= the current line to be completed
 
def ResultsListCompleting(sample,CN,BF,RR,listS,line):
    if (line[4]=="<DEL>"):
        if int(CN)==0: #Homo-deletion
            ValueToAdd=("1/1:"+str(round(float(BF),2))+":"+str(round(float(RR),2)))
            indexToKeep=listS.index(sample)+9 # the most 9 corresponds to the informative columns of the vcf .
            line[indexToKeep]=ValueToAdd
        else: #Hetero-deletion
            ValueToAdd=("0/1:"+str(round(float(BF),2))+":"+str(round(float(RR),2)))
            indexToKeep=listS.index(sample)+9
            line[indexToKeep]=ValueToAdd

    elif (line[4]=="<DUP>"): 
        ValueToAdd=("0/1:"+CN+":"+str(round(float(BF),2))+":"+str(round(float(RR),2)))
        indexToKeep=listS.index(sample)+9
        line[indexToKeep]=ValueToAdd
    return(line)


##############################################################################################################
######################################### Script Body ########################################################
##############################################################################################################
###################################
def main(argv):
    ##########################################
    # A) ARGV parameters definition
    callResultsPath = ''
    bayesThreshold=''
    outputFile =''

    try:
        opts, args = getopt.getopt(argv,"h:c:b:o:",["help","callsFile=","BFthreshold=","outputfile="])
    except getopt.GetoptError:
        print('python3.6 STEP_3_VCFFormatting_Bedtools.py -c <callsFile> -b <BFthreshold> -o <outputfile>')
        sys.exit(2)
    for opt, value in opts:
        if opt == '-h':
            print("COMMAND SUMMARY:"			
            +"\n This script allows to format the results of CNV calls obtained with Bedtools/ExomeDepth in VCF."
            +"\n"
            +"\n USAGE:"
            +"\n python3.6 STEP_3_VCFFormatting_Bedtools.py -c <callsFile> -b <BFthreshold> -o <outputfile>"
            +"\n"
            +"\n OPTIONS:"
            +"\n	-c : A tsv file obtained in STEP2 (CNV calling results). Please indicate the full path.(15 columns)"
            +"\n	-b : Bayes factor filtering threshold (all CNVs with a lower BF level will be removed from the analysis)."
            +"\n	-o : The path where create the new output file for the current analysis.")
            sys.exit()
        elif opt in ("-c", "--callsFile"):
            callResultsPath=value
        elif opt in ("-b", "--BFthreshold"):
            bayesThreshold=value
        elif opt in ("-o", "--outputfile"):
            outputFile=value

    #Check that all the arguments are present.
    logger.info('CNVs calling results file path is %s', callResultsPath)
    logger.info('BF threshold is %s ', bayesThreshold)
    logger.info('Output file path is %s ', outputFile)

    #####################################################
    # A) Input file format check
    logger.info("Input file format check")
    tabToTreat=InputParseAndSanityCheck(callResultsPath,outputFile)

    #####################################################
    # B)Filtering according to the Bayes Factor threshold chosen by the user in the function parameters.
    logger.info("Filtering")
    minBF=int(bayesThreshold)
    CNVTableBFfilter=tabToTreat[tabToTreat.BF>minBF]
    logger.info("1) CNVs Number obtained after BF>=%s, filtering=%s/%s",minBF,len(CNVTableBFfilter),len(tabToTreat))

    #####################################################
    # C)Appropriate copy numbers allocation according to the read ratios.
    # Warning filtering of deletions with RR>0.75.
    CNVTableBFfilter.reset_index(drop=True, inplace=True)
    CNVTableBFfilter.loc[:,"CN"]=np.repeat(4,len(CNVTableBFfilter))#CN obsolete allow to delete DEL with RR>0.75
    CNVTableBFfilter.loc[CNVTableBFfilter["type"]=="duplication","CN"]=3
    CNVTableBFfilter.loc[CNVTableBFfilter["reads.ratio"]<0.75,"CN"]=1
    CNVTableBFfilter.loc[CNVTableBFfilter["reads.ratio"]<0.25,"CN"]=0
    CNVTableAllFilter=CNVTableBFfilter[CNVTableBFfilter["CN"]!=4]
    logger.info("2) CNVs Number obtained after copy number attribution  = %s/%s",len(CNVTableAllFilter),len(tabToTreat))

    #####################################################
    # D) Standardization STEP
    #Creation of a chromosome column not containing chr at the beginning of the term.
    CNVTableAllFilter["#CHROM"]=CNVTableAllFilter["chromosome"].str.replace("chr","")

    #Position correction => padding removal
    CNVTableAllFilter["POS"]=CNVTableAllFilter["start"]+9 #ExomeDepth automatically adds 1 more base to the start.
    CNVTableAllFilter["end2"]=CNVTableAllFilter["end"]-10

    #####################################################
    # E) Dictionnary Creation 
    #Key : CNV identifier: "CHR:start-end"
    #Value : list of patients characteristics affected by a cnv at this position. For each patient: SampleName_CN_BF_RR
    Dict={}
    for index, row in CNVTableAllFilter.iterrows():
        Key=row["id"]
        Value=row["sample"]+"_"+str(row["CN"])+"_"+str(row["BF"])+"_"+str(row["reads.ratio"])
        Dict.setdefault(Key,[]).append(Value)
    logger.info("3) Number of dictionnary Keys = %s",len(Dict))

    #####################################################
    # F) loop over the dictionary keys to create the final vcf.

    resultlist=[]
    sampleList=list(np.unique(CNVTableAllFilter["sample"]))
    for key, value in Dict.items():
        #######################################
        ## Key processing
        #chromosome treatment
        chrom=re.sub("^chr([\w]{1,2}):[\d]{3,9}-[\d]{3,9}$","\\1", key)
        #pos
        pos=re.sub("^chr[\w]{1,2}:([\d]{3,9})-[\d]{3,9}","\\1", key)
        #end
        end=re.sub("^chr[\w]{1,2}:[\d]{3,9}-([\d]{4,9})","\\1", key)

        #Empty lists initialization for identical positions between DUP and DEL within the cohort.
        firstline=[]
        secondline=[]

        #######################################
        ## Value processing
        for i in value:
            info_list=i.split("_")
            sample=info_list[0]          
            CN=info_list[1]
            BF=info_list[2]
            RR=info_list[3]          
            #First list initialisation           
            if len(firstline)==0:                
                firstline=ResultsListInitialisation(sample,chrom,pos,key,end,CN,BF,RR,sampleList)  
            else:
                #add information to the first list
                if ((firstline[4]=="<DEL>") and (int(CN)<2)) or ((firstline[4]=="<DUP>") and (int(CN)>2)):
                    firstline=ResultsListCompleting(sample,CN,BF,RR,sampleList,firstline)
                #Second list initialisation      
                elif len(secondline)==0:
                    secondline=ResultsListInitialisation(sample,chrom,pos,key,end,CN,BF,RR,sampleList)
                #add information to the second list
                elif len(secondline)>0:
                    secondline=ResultsListCompleting(sample,CN,BF,RR,sampleList,secondline)
                else:
                    logger.error("Unable to treat the CNV identified at the position:"+key+" for the patient:"+i+"."
                     +"\n Please check the correct format of the latter.")
                    sys.exit()

        #adding the results of the current key to the final list
        if len(secondline)>0:
            resultlist.append(firstline)
            resultlist.append(secondline)
        else:
            resultlist.append(firstline)   
            
    colNames=["#CHROM","POS","ID","REF","ALT","QUAL","FILTER","INFO","FORMAT"]+sampleList
    results=pd.DataFrame(resultlist, columns=colNames)# transform list to dataframe

    #####################################################
    # G) sorting
    results["CHR"]=results["#CHROM"]
    results["CHR"]=results["CHR"].str.replace('X', '23')
    results["CHR"]=results["CHR"].str.replace('Y', '24')
    results["CHR"]=results["CHR"].str.replace('M', '25')
    results["CHR"]=results["CHR"].astype(int)
    results["POS"]=results["POS"].astype(int)
    results=results.sort_values(by=["CHR","POS"])
    results=results.drop(columns=["CHR"])    

    #####################################################
    # H) Header definition
    header = """##fileformat=VCFv4.3
##fileDate="""+now+"""
##source="""+sys.argv[0]+"""
##reference=file:///seq/references/
##ALT=<ID=DEL,Description="Deletion">
##ALT=<ID=DUP,Description="Duplication">
##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type of structural variant">
##INFO=<ID=END,Number=1,Type=Integer,Description="End position of the variant described in this record">
##FORMAT=<ID=GT,Number=1,Type=Integer,Description="Genotype">
##FORMAT=<ID=CN,Number=1,Type=Integer,Description="Copy number genotype for imprecise events">
##FORMAT=<ID=BF,Number=1,Type=Float,Description="Bayes Factor from stuctural variant prediction">
##FORMAT=<ID=RR,Number=1,Type=Float,Description="Reads ratio of structural variant">
"""

    #####################################################
    # I) Vcf saving
    output_VCF =os.path.join(outputFile,"CNVResults_BedtoolsExomeDepth_"+str(len(np.unique(CNVTableAllFilter["sample"])))+"samples_"+now+".vcf")
    with open(output_VCF, 'w') as vcf:
        vcf.write(header)

    results.to_csv(output_VCF, sep="\t", mode='a', index=False)

if __name__ =='__main__':
    main(sys.argv[1:])
    

