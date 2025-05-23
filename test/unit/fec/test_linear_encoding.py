#
# SPDX-FileCopyrightText: Copyright (c) 2021-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0#

import unittest
import numpy as np
import tensorflow as tf
from sionna.phy import config
from sionna.phy.fec.utils import load_parity_check_examples
from sionna.phy.fec.linear import LinearEncoder
from sionna.phy.mapping import BinarySource
from sionna.phy.fec.polar.utils import generate_dense_polar, generate_5g_ranking
from sionna.phy.fec.polar import PolarEncoder

class TestGenericLinearEncoder(unittest.TestCase):
    """Test Generic Linear Encoder."""

    def test_dim_mismatch(self):
        """Test against inconsistent inputs. """
        id = 2
        pcm, k, _, _ = load_parity_check_examples(id)
        bs = 20
        enc = LinearEncoder(pcm, is_pcm=True)

        # test for non-invalid input shape
        with self.assertRaises(BaseException):
            x = enc(tf.zeros([bs, k+1]))

        # test for non-binary matrix
        with self.assertRaises(BaseException):
            pcm[0,0]=2
            enc = LinearEncoder(pcm) # we interpret the pcm as gm for this test

        # test for non-binary matrix
        with self.assertRaises(BaseException):
            pcm[0,0]=2
            enc = LinearEncoder(pcm, is_pcm=True)

    def test_tf_fun(self):
        """Test that tf.function works as expected and XLA is supported."""

        @tf.function
        def run_graph(u):
            c = enc(u)
            return c

        @tf.function(jit_compile=True)
        def run_graph_xla(u):
            c = enc(u)
            return c

        id = 2
        pcm, k, _, _ = load_parity_check_examples(id)
        bs = 20
        enc = LinearEncoder(pcm, is_pcm=True)
        source = BinarySource()

        u = source([bs,k])
        run_graph(u)
        run_graph_xla(u)

    def test_dtypes_flexible(self):
        """Test that encoder supports variable dtypes and
        yields same result."""

        dt_supported = (tf.float16, tf.float32, tf.float64, tf.int32, tf.int64)

        id = 2
        pcm, k, _, _ = load_parity_check_examples(id)
        bs = 20
        enc_ref = LinearEncoder(pcm, is_pcm=True, precision="single")
        source = BinarySource()

        u = source([bs, k])
        c_ref = enc_ref(u)

        for prec in ("single", "double"):
            for dt in dt_supported:
                enc = LinearEncoder(pcm, is_pcm=True, precision=prec)
                u_dt = tf.cast(u, dt)
                c = enc(u_dt)

                c_32 = tf.cast(c, tf.float32)

                self.assertTrue(np.array_equal(c_ref.numpy(), c_32.numpy()))

    def test_multi_dimensional(self):
        """Test against arbitrary input shapes.

        The encoder should only operate on axis=-1.
        """
        id = 3
        pcm, k, n, _ = load_parity_check_examples(id)
        shapes =[[k],[10, 20, 30, k], [1, 40, k], [10, 2, 3, 4, 3, k]]
        enc = LinearEncoder(pcm, is_pcm=True)
        source = BinarySource()

        for s in shapes:
            u = source(s)
            u_ref = tf.reshape(u, [-1, k])

            c = enc(u) # encode with shape s
            c_ref = enc(u_ref) # encode as 2-D array
            s[-1] = n
            c_ref = tf.reshape(c_ref, s)
            self.assertTrue(np.array_equal(c.numpy(), c_ref.numpy()))

        # and verify that wrong last dimension raises an error
        with self.assertRaises(tf.errors.InvalidArgumentError):
            s = [10, 2, k-1]
            u = source(s)
            x = enc(u)

    def test_against_baseline(self):
        """Test that PolarEncoder leads to same result.
        """
        bs = 1000
        k = 57
        n = 128

        # generate polar frozen positions
        f,_ = generate_5g_ranking(k, n)

        enc_ref = PolarEncoder(f, n) # reference encoder

        # get polar encoding matrix
        pcm, gm = generate_dense_polar(f, n, verbose=False)
        enc = LinearEncoder(gm)

        # draw random info bits
        source = BinarySource()
        u = source([bs, k])

        # encode u with both encoders
        c = enc(u)
        c_ref = enc_ref(u)

        # and compare results
        self.assertTrue(np.array_equal(c.numpy(), c_ref.numpy()))

    def test_random_matrices(self):
        """Test against random parity-check matrices."""

        n_trials = 100 # test against multiple random pcm realizations
        bs = 100
        k = 89
        n = 123
        source = BinarySource()

        for _ in range(n_trials):
            # sample a random matrix
            pcm = config.np_rng.uniform(low=0, high=2, size=(n-k, n)).astype(int)

            # catch internal errors due to non-full rank of pcm (randomly
            # sampled!)
            # in this test we only test that if the encoder initalization
            # succeeds and the resulting encoder object produces valid codewords
            try:
                enc = LinearEncoder(pcm, is_pcm=True)
            except:
                pass # ignore this pcm realization

            u = source([bs, k])
            c = enc(u)
            # verify that all codewords fullfil all parity-checks
            c = tf.expand_dims(c, axis=2)
            pcm = tf.expand_dims(tf.cast(pcm, tf.float32),axis=0)
            s = tf.matmul(pcm,c).numpy()
            s = np.mod(s, 2)
            self.assertTrue(np.sum(np.abs(s))==0)
