# Content of this file adapted from https://github.com/hmiemad/robust_Gaussian_fit ,
# thanks to the author for sharing.
#
# Copyright (c) 2022 hmiemad
#
# MIT License
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import numpy


###############################################################################
############################ PRIVATE FUNCTIONS ################################
###############################################################################

#############################################################
def normal_erf(x, mu=0, sigma=1, depth=50):
    ele = 1.0
    normal = 1.0
    x = (x - mu) / sigma
    erf = x
    for i in range(1, depth):
        ele = - ele * x * x / 2.0 / i
        normal = normal + ele
        erf = erf + ele * x / (2.0 * i + 1)

    return (numpy.clip(normal / numpy.sqrt(2.0 * numpy.pi) / sigma, 0, None),
            numpy.clip(erf / numpy.sqrt(2.0 * numpy.pi) / sigma, -0.5, 0.5))


#############################################################
def truncated_integral_and_sigma(x):
    n, e = normal_erf(x)
    return numpy.sqrt(1 - n * x / e)


###############################################################################
############################ PUBLIC FUNCTIONS #################################
###############################################################################

#############################################################
def robustGaussianFit(X, mu=None, sigma=None, bandwidth=2.0, eps=1.0e-5):
    """
    Fits a single principal gaussian component around a starting guess point
    in a 1-dimensional gaussian mixture of unknown components with EM algorithm

    Args:
        X (numpy.array): A sample of 1-dimensional mixture of gaussian random variables
        mu (float, optional): Expectation. Defaults to None.
        sigma (float, optional): Standard deviation. Defaults to None.
        bandwidth (float, optional): Hyperparameter of truncation. Defaults to 2.
        eps (float, optional): Convergence tolerance. Defaults to 1.0e-5.

    Returns:
        mu,sigma: mean and stdev of the gaussian component
    """

    if mu is None:
        # median is an approach as robust and naïve as possible to Expectation
        mu = numpy.median(X)
        if mu == 0:
            raise Exception("cannot fit")
    mu_0 = mu + 1

    if sigma is None:
        # rule of thumb
        sigma = numpy.std(X) / 3
    sigma_0 = sigma + 1

    bandwidth_truncated_normal_sigma = truncated_integral_and_sigma(bandwidth)

    while abs(mu - mu_0) + abs(sigma - sigma_0) > eps:
        # loop until tolerence is reached
        """
        create a uniform window on X around mu of width 2*bandwidth*sigma
        find the mean of that window to shift the window to most expected local value
        measure the standard deviation of the window and divide by the sddev of a truncated gaussian distribution
        """
        Window = numpy.logical_and(X - mu - bandwidth * sigma < 0, X - mu + bandwidth * sigma > 0)
        if not Window.any():
            raise Exception("cannot fit")
        mu_0, mu = mu, numpy.average(X[Window])
        var = numpy.average(numpy.square(X[Window] - mu))
        sigma_0, sigma = sigma, numpy.sqrt(var) / bandwidth_truncated_normal_sigma

    return (mu, sigma)
