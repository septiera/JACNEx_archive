<p align="center">
  <a href="https://github.com/septiera/Dev_InfertilityCohort_CNVAnalysis"><img alt="ndim" src="https://www.google.com/search?q=TIMC&tbm=isch&ved=2ahUKEwjh08eG2e_zAhWW0oUKHfZ3AMEQ2-cCegQIABAA&oq=TIMC&gs_lcp=CgNpbWcQAzIHCCMQ7wMQJzIFCAAQgAQyBQgAEIAEMgUIABCABDIFCAAQgAQyBQgAEIAEMgUIABCABDIFCAAQgAQyBQgAEIAEMgUIABCABDoECAAQHjoKCCMQ7wMQ6gIQJzoECAAQQzoICAAQgAQQsQM6CwgAEIAEELEDEIMBUJUHWIIQYKIRaAFwAHgAgAFriAHeA5IBAzMuMpgBAKABAaoBC2d3cy13aXotaW1nsAEKwAEB&sclient=img&ei=A_N7YaHGBZallwT274GIDA&bih=810&biw=1265&client=firefox-b-e#imgrc=mHSwLr8DdNnigM" width="50%"></a>
  <p align="center">CNV calls for exome sequencing data from human cohort.</p>
</p>

The pipeline enables germline Copy Number Variations (CNVs) to be called from human exome sequencing data.
The input data of this pipeline are Binary Alignment Maps (BAM) and Browser Extensible Data (BED) containing the intervals associated with the canonical transcripts.
For more information how obtaining the different files see https://github.com/ntm/grexome-TIMC-Primary

### EXAMPLE USAGE:

* STEP 0 : Interval bed creation
This step consists in creating an interval file in the bed format.
It performs a verification of the input bed file, performs a padding +-10pb and sorts the data in genomic order.
It is necessary to respect the format of the reference genome name for pipeline interoperability at each new process started.
```
BED="canonicalTranscripts.bed.gz"
GENOMEV="GRCH38_vXXX"
OUTPUT="~/Scripts/"
/bin/time -v ~/FolderContainsScript/python3.6 STEP_0_IntervalList.py -b $BED -n $GENOMEV -o $OUTPUT 2> ./.err
```

* STEP 1 : Counting reads
This step uses the bam files to record the number of reads overlapping the intervals present in the bed file created in step 0.
It will create a new folder for storing the results. 
This script uses Bedtoolsv2.18 and its multibamCov program.
It is executed in parallel to reduce the process time.
Warning: the number of cpu used for parallelization is optimized.
If the number of cpu is increased manually within the script it can lead to waiting times increasing the global process time.
The script provides a read count file for each sample analyzed (tsv files).

```
INTERVAL="~/STEP0_GRCH38_vXXX_Padding10pb_NBexons_Date.bed"
BAM="~/BAMs/"
OUTPUT="~/SelectOutputFolder/"
/bin/time -v ~/FolderContainsScript/python3.6 STEP_1_CollectReadCounts_Bedtools.py -i $INTERVAL -b $BAM -o $OUTPUT 2> ./.err 
```

* STEP 2 : CNV Calling
This step performs the CNV calling.
However it uses the DECON/ExomeDepth script in R modified to allow inserting different inputs (tsv instead of Rdata).
It has also been modified by adding a sanity check of the input files.
The R script does not have the part allowing to generate the plots anymore.
The output file is in tsv format and contains the complete CNV calling results for all samples.
```
INTERVAL="~/STEP0_GRCH38_v104_Padding10pb_NBexons_Date.bed"
READF="~/Bedtools/"
OUTPUT="~/SelectOutputFolder/"
/bin/time -v ~/FolderContainsScript/python3.6 STEP_2_GermlineCNVCaller_DECoNBedtools.py -i $BED -r $READF -o $OUTPUT 2> ./.err
```

* STEP 3 : VCF Formatting
This step allows the conversion of CNV calling results into vcfv4.3 format that can be interpreted by the VEP software (annotation of structural variants) 
The Bayes Factor(BF) parameter is user selectable. It will be necessary to perform a first filtering of the CNV. 
```
CALL="~/Results_BedtoolsCallingCNVExomeDepth_Date.tsv"
BF="20"
OUTPUT="~/SelectOutputFolder/Calling_results_Bedtools_Date/"
/bin/time -v ~/FolderContainsScript/python3.6 STEP_3_VCFFormatting_Bedtools.py -c $CALL -b $BF -o $OUTPUT 2> ./.err
```

### CONFIGURATION:

### DEPENDENCIES:



