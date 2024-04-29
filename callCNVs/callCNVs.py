import concurrent.futures
import logging
import math
import numpy
import traceback

####### JACNEx modules
import callCNVs.transitions

# set up logger, using inherited config
logger = logging.getLogger(__name__)


###############################################################################
############################ PUBLIC FUNCTIONS #################################
###############################################################################
######################################
# applyHMM
# Processes CNV calls for a given set of samples in parallel using the HMM Viterbi algorithm.
# Args:
# - samples (list[strs]): List of sample identifiers.
# - autosomeExons (list[str, int, int, str]): exon on autosome infos [chr, START, END, EXONID].
# - gonosomeExons (list[str, int, int, str]): exon on gonosome infos.
# - likelihoods_A (dict): key==sample ID, value==Likelihoods for autosomal chromosomes,
#                         numpy.ndarray 2D [floats], dim = NbofExons * NbOfCNStates
# - likelihoods_G (dict): key==sample ID, value==Likelihoods for gonosomal chromosomes
# - priors (list[floats]): prior probabilities for each CN status.
# - transMatrix (numpy.ndarray[floats]): Transition matrix for the HMM Viterbi algorithm.
# - jobs (int): Number of jobs to run in parallel.
# - dmax (int): Maximum distance threshold between exons.
#
# Returns a tuple of two lists: The first list contains CNV information for autosomal chromosomes,
# and the second list for gonosomal chromosomes. Each list contains tuples with CNV information:
# [CNType, exonIndexStart, exonIndexEnd, bestPathProbabilities, sampleName].
def applyHMM(samples, autosomeExons, gonosomeExons, likelihoods_A, likelihoods_G, priors, transMatrix, jobs, dmax):
    CNVs_A = []
    CNVs_G = []
    paraSample = min(math.ceil(jobs / 2), len(samples))
    logger.info("%i samples => will process %i in parallel", len(samples), paraSample)

    # with concurrent.futures.ProcessPoolExecutor(paraSample) as pool:
    #     processSamps(samples, autosomeExons, likelihoods_A, transMatrixNoVoid, priors, pool, CNVs_A, dmax)
    #     processSamps(samples, gonosomeExons, likelihoods_G, transMatrixNoVoid, priors, pool, CNVs_G, dmax)
    # return (CNVs_A, CNVs_G)

    for sampID in samples:
        try:
            if sampID in likelihoods_A:
                CNVs_A.extend(callCNVsOneSample(likelihoods_A[sampID], transMatrix, priors, sampID, autosomeExons, dmax))
            if sampID in likelihoods_G:
                CNVs_G.extend(callCNVsOneSample(likelihoods_G[sampID], transMatrix, priors, sampID, gonosomeExons, dmax))
        except Exception as e:
            logger.error("callCNVsOneSample() failed for sample %s: %s", sampID, str(e))
            traceback.print_exc()
            raise
    countCNVs(CNVs_A)
    countCNVs(CNVs_G)
    return (CNVs_A, CNVs_G)


###############################################################################
############################ PRIVATE FUNCTIONS ################################
###############################################################################
######################################
# processSamps
# Processes a specific type of chromosome (either autosomal or gonosomal) for CNV calls.
# This function iterates over each sample to submit CNV calling tasks to a multiprocessing pool.
#
# Args:
# - samples (list[strs]): A list of sample identifiers.
# - exons (list[str, int, int, str]): exon on autosome infos [chr, START, END, EXONID].
# - likelihoods (dict): key==sample ID, value==Likelihoods,
#                       numpy.ndarray 2D [floats], dim = NbofExons * NbOfCNStates
# - transMatrix (numpy.ndarray[floats]): A transition matrix used in the HMM Viterbi algorithm.
# - pool (concurrent.futures.Executor): A concurrent executor for parallel processing.
# - CNVs (list[str, int, int, int, floats, str]): CNV infos [CNType, exonStart, exonEnd, pathProb, sampleName]
# - dmax (int): Maximum distance threshold between exons.
def processSamps(samples, exons, likelihoods, transMatrix, priors, pool, CNVs, dmax):
    for sampID in samples:
        # check if the sample ID is present in the likelihoods dictionary
        if sampID not in likelihoods.keys():
            logger.debug("no CNV calling for sample %s", sampID)
            continue
        # submit a task for processing the chromosome data for the current sample
        # task is submitted to the provided process pool for parallel execution
        futureRes = pool.submit(callCNVsOneSample(likelihoods[sampID], transMatrix, priors, sampID, exons, dmax))
        # add a callback to the future object
        # once the task is complete, the concatCNVs function will be called with the result
        # the concatCNVs function will handle the aggregation of CNVs from the result
        futureRes.add_done_callback(lambda future: concatCNVs(future, CNVs))


######################################
# concatCNVs
# A callback function for processing the result of a Viterbi algorithm task.
# Extracts the result from the Future object and appends it to a global CNVs list.
#
# Args:
# - futureSampCNVExtract (concurrent.futures.Future): A Future object for an
#    asynchronous CallCNVsOneSample task.
# - CNVs (list): Global list to which the results are appended.
#    Each element is a tuple representing CNV information.

# No return value; updates the CNVs list in place.
def concatCNVs(futureSampCNVExtract, CNVs):
    e = futureSampCNVExtract.exception()
    if e is not None:
        logger.warning("Failed callCNVsOneSample %s", str(e))
        raise(e)
    else:
        viterbiRes = futureSampCNVExtract.result()
        countCNVs(viterbiRes)
        # append each CNV from the result to the global CNVs list
        for cnv in range(len(viterbiRes)):
            CNVs.append(viterbiRes[cnv])


######################################
# countCNVs
# Counts the occurrences of each CNV type called for a sample and logs the result.
#
# Args:
# - sampCNVs (list of lists): CNV data for a sample. Each inner list contains CNV information.
def countCNVs(sampCNVs):
    # cnCounts[i] == number of called CNVs with CN==i
    cnCounts = [0, 0, 0, 0]
    for CNV in sampCNVs:
        cn = CNV[0]
        cnCounts[cn] += 1

    cn_list = [f"CN{cn}:{cnCounts[cn]}" for cn in range(cnCounts)]
    cn_str = ', '.join(cn_list)
    logger.debug("Done callCNvs for %s: %s", sampCNVs[0][4], cn_str)


######################################
# callCNVsOneSample:
# call and return CNVs for a single sample.
# This function implements the Viterbi algorithm to find the most likely sequence of
# states (copy-number states) given the observations (likelihoods).
#
# The underlying HMM is defined by:
# - one state per copy number (0==homodel, 1==heterodel, 2==WT, 3==CN3+==DUP)
# - emission likelihoods of the sample's FPM in each state and for each exon, which have
#   been pre-calculated;
# - transition probabilities that depend on the distance to the next exon - they begin when
#   distance=0 at the "base" values defined in transMatrix, and are smoothly adjusted following
#   a power law until they reach the prior probabilities at dist dmax
#
# Args:
# - likelihoods (ndarray[floats] dim NbExons*NbStates): pseudo-emission probabilities
#   (likelihoods) of each state for each exon for one sample.
# - transMatrix (ndarray[floats] dim NbStates*NbStates): base transition probas between states
# - priors (ndarray dim NbStates): prior probabilities for each state
# - sampleID [str]
# - exons [list of lists[str, int, int, str]]: exon infos [chr, START, END, EXONID].
# - dmax [int]: param for adjustTransMatrix()
#
# Returns:
# - CNVs (list of list[int, int, int, float, str]): list of called CNVs,
#   a CNV is a list [CNVType, firstExonIndex, lastExonIndex, qualityScore, sampleID].
def callCNVsOneSample(likelihoods, sampleID, transMatrix, priors, exons, dmax):
    try:
        CNVs = []
        NbStates = len(transMatrix)
        # sanity
        if NbStates != likelihoods.shape[1]:
            logger.error("NbStates in transMatrix and in likelihoods inconsistent")
            raise

        # Step 1: Initialize variables
        # probsPrev[s]: probability of the most likely path ending in state s at the previous exon,
        # initialize path root at CN2
        probsPrev = numpy.zeros(NbStates, dtype=numpy.float128)
        probsPrev[2] = 1
        # probsCurrent[s]: same, ending at current exon
        probsCurrent = numpy.zeros(NbStates, dtype=numpy.float128)
        # chrom and end of previous exon - init at -dmax so first exon uses the priors
        prevChrom = exons[0][0]
        prevEnd = -dmax

        # temp data structures used by buildCNVs() and reset whenever it is called,
        # see buildCNVs() spec for info
        calledExons = []
        path = []
        bestPathProbas = []
        CN2PathProbas = []

        # Step 2: viterbi forward algorithm
        for exonIndex in range(len(exons)):
            if likelihoods[exonIndex, 0] == -1:
                # exon is no-call => skip
                continue

            if exons[exonIndex][0] != prevChrom:
                # only need to buildCNVs if at least one exon's bestPath-to-CN2 was non-CN2
                if any((p[2] != 2) for p in path):
                    CNVs.extend(buildCNVs(calledExons, path, bestPathProbas, CN2PathProbas,
                                          bestPathProbas[-1].argmax(), sampleID))
                # reinit
                probsPrev[:] = 0
                probsPrev[2] = 1
                prevChrom = exons[exonIndex][0]
                prevEnd = -dmax
                calledExons = []
                path = []
                bestPathProbas = []
                CN2PathProbas = []

            # adjust transition probabilities
            distFromPrevEx = exons[exonIndex][1] - prevEnd - 1
            adjustedTransMatrix = callCNVs.transitions.adjustTransMatrix(transMatrix, priors, distFromPrevEx, dmax)

            # calculate proba of the most likely paths ending in each state for current exon

            # accumulators with current exon data for populating the buildCNVs() structures:
            # populating these must be delayed until after possible backtrack+reset with
            # previous exon data
            # bestPrevState defaults to CN2
            bestPrevState = numpy.full(NbStates, 2, dtype=numpy.int8)
            # bestPathProbas will just copy probsCurrent
            CN2PathProba = 0

            for currentState in range(NbStates):
                probMax = -1
                prevStateMax = -1
                for prevState in range(NbStates):
                    # probability of path coming from prevState to currentState
                    prob = (probsPrev[prevState] *
                            adjustedTransMatrix[prevState, currentState] *
                            likelihoods[exonIndex, currentState])
                    if prob > probMax:
                        probMax = prob
                        prevStateMax = prevState
                    if (currentState == 2) and (prevState == 2):
                        CN2PathProba = prob

                # save most likely path leading to currentState
                probsCurrent[currentState] = probMax
                if probMax > 0:
                    bestPrevState[currentState] = prevStateMax
                # else keep default CN2 as bestPrevState
            print("Done with exon ", exonIndex, ", probsCurrent=", probsCurrent,
                  ", bestPrevState=", bestPrevState, ", CN2PathProba=", CN2PathProba)

            # if all states at currentExon have the same predecessor state and that state is CN2:
            # backtrack from [previous exon, CN2] if needed and reset
            if numpy.all(bestPrevState == 2):
                if any((p[2] != 2) for p in path):
                    CNVs.extend(buildCNVs(calledExons, path, bestPathProbas, CN2PathProbas, 2, sampleID))
                # else the best path is necessarily all-CN2 => there's nothing to build, but in any case
                # adjust probas so paths start at CN2 in previous exon with a proba of 1, and reset
                # all buildCNVs() structures
                if len(calledExons) > 0:
                    probsCurrent[:] /= probsPrev[2]
                    CN2PathProba /= CN2PathProbas[-1]
                    calledExons = []
                    path = []
                    bestPathProbas = []
                    CN2PathProbas = []
                    print("adjusted probas for exon ", exonIndex, ", new probs=", probsCurrent,
                          ", CN2PathProba=", CN2PathProba)

            # OK, update all structures and move to next exon
            numpy.copyto(probsPrev, probsCurrent)
            prevEnd = exons[exonIndex][2]
            calledExons.append(exonIndex)
            path.append(bestPrevState)
            bestPathProbas.append(probsCurrent.copy())
            CN2PathProbas.append(CN2PathProba)

        # Final CNVs for the last exons
        if any((p[2] != 2) for p in path):
            print("FINALRESET")
            CNVs.extend(buildCNVs(calledExons, path, bestPathProbas, CN2PathProbas,
                                  bestPathProbas[-1].argmax(), sampleID))

        return(CNVs)

    except Exception as e:
        logger.error("callCNVsOneSample failed for sample %s in exon %i: %s", sampleID, exonIndex, repr(e))
        raise Exception(sampleID)


######################################
# buildCNVs
# Identify CNVs (= consecutive exons with the same CN) in a most-likely path, and
# calculate the associated "qualityScore" (see below).
# Requirement: the called exon preceding calledExons[0] (called the "path root") must
# be in state CN2 in every most likely path.
#
# Args:
# - calledExons [list of ints]: list of called exonIndexes to process here
# - path (list of len(calledExons) ndarrays of NbStates ints):
#   path[e][s] == state of called exon preceding calledExons[e] that produces the max
#   proba for state s at exon calledExons[e]
# - bestPathProbas (list of len(calledExons) ndarrays of NbStates floats):
#   bestPathProbas[e][s] == proba of most likely path ending in state s at exon
#   calledExons[e] and starting at the path root
# - CN2PathProbas (list of len(calledExons) floats): CN2FromCN2Probas[e] == proba of
#   path ending in state CN2 at exon calledExons[e], starting at path root, and staying
#   in state CN2 all along
# - lastState [int]: state with the max probability for the last exon in calledExons
# - sampleID [str]
#
# Returns a list of CNVs, a CNV == [CNType, startExon, endExon, qualityScore, sampleID]:
# - CNType is 0-3 (== CN)
# - startExon and endExon are indexes (in the global exons list) of the first and
#   last exons defining this CNV
# - qualityScore = log of ratio between the proba of most likely path between the called
#   exons immediately preceding and immediately following the CNV, and the proba of
#   the CN2-only path between the same exons
def buildCNVs(calledExons, path, bestPathProbas, CN2PathProbas, lastState, sampleID):
    CNVs = []

    print("CalledEx=", calledExons, ", path=", path, ", bestPathProbas:", bestPathProbas,
          ", CN2PathProbas=", CN2PathProbas, ", lastState=", lastState)

    if lastState != 2:
        # can only happen when called with the last exon of a chrom: append bogus last
        # exon in CN2 state, copying the path proba
        calledExons.append(-1)
        path.append(numpy.array([0, 0, lastState, 0]))
        bestPathProbas.append(numpy.array([0, 0, bestPathProbas[-1][lastState], 0]))
        CN2PathProbas.append(CN2PathProbas[-1])

    # build ndarray of states that form the most likely path, must start from the end
    mostLikelyStates = numpy.zeros(len(calledExons), dtype=numpy.int8)
    mostLikelyStates[-1] = 2
    currentState = 2
    for cei in range(len(calledExons) - 1, 0, -1):
        currentState = path[cei][currentState]
        mostLikelyStates[cei - 1] = currentState

    # now walk through the path of most likely states, constructing CNVs as we go
    currentState = mostLikelyStates[0]
    firstExonInCurrentState = 0

    for cei in range(1, len(calledExons)):
        if mostLikelyStates[cei] == currentState:
            # next exon is in same state, NOOP
            continue
        else:
            if (currentState != 2):
                # we changed states and current wasn't CN2, create CNV
                # score = log of ratio between best path proba and CN2-only path proba
                qualityScore = bestPathProbas[cei][mostLikelyStates[cei]] / CN2PathProbas[cei]
                if firstExonInCurrentState > 0:
                    # we want the probas of the paths starting at the exon immediately
                    # preceding the CNV, not starting at the path root
                    qualityScore /= bestPathProbas[firstExonInCurrentState - 1][mostLikelyStates[firstExonInCurrentState - 1]]
                    qualityScore *= CN2PathProbas[firstExonInCurrentState - 1]
                qualityScore = math.log(qualityScore)
                CNVs.append([currentState, calledExons[firstExonInCurrentState],
                             calledExons[cei - 1], qualityScore, sampleID])
            # in any case we changed states, update accumulators
            currentState = mostLikelyStates[cei]
            firstExonInCurrentState = cei

    return(CNVs)
