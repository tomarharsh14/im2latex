#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
    Copyright 2017 Sumeet S Singh

    This file is part of im2latex solution by Sumeet S Singh.

    This program is free software: you can redistribute it and/or modify
    it under the terms of the Affero GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    Affero GNU General Public License for more details.

    You should have received a copy of the Affero GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
Created on Mon Jul 24 12:28:55 2017

@author: Sumeet S Singh
"""

import os
import time
from six.moves import cPickle as pickle
import tensorflow as tf
from keras import backend as K
from keras.preprocessing import image
from Im2LatexModel import build_image_context
from data_reader import BatchImageIterator2, ImagenetProcessor
from hyper_params import make_hyper
import tf_commons as tfc
import argparse as arg
import dl_commons as dlc
import pandas as pd

def get_df(params):
    image_features_folder = params.vgg16_folder
    raw_data_folder = params.raw_data_folder
    image_features_folder = params.vgg16_folder
    image_list = [os.path.splitext(s)[0]+'.png' for s in filter(lambda s: s.endswith('.pkl'),os.listdir(image_features_folder))]
    df_train = pd.read_pickle(os.path.join(params.raw_data_folder, 'df_train.pkl'))
    df_test = pd.read_pickle(os.path.join(params.raw_data_folder, 'df_test.pkl'))
    df = df_train.append(df_test)

    df = df[~df.image.isin(image_list)]
    print 'Dataframe Shape = %s'%(df.shape,)
    df.bin_len = df.bin_len.max()
    return df

def run(params):
    HYPER = make_hyper(params)
    image_folder = params.image_folder
    raw_data_folder = params.raw_data_folder
    image_features_folder = params.vgg16_folder

    b_it = BatchImageIterator2(
                        raw_data_folder,
                        image_folder, 
                        HYPER, 
                        image_processor=ImagenetProcessor(HYPER),
                        df=get_df(params),
                        num_steps=params.num_steps,
                        num_epochs=params.num_epochs)

    graph = tf.Graph()
    with graph.as_default():

        ## config=tf.ConfigProto(log_device_placement=True)
        ## config.gpu_options.allow_growth = True
        tf_session = tf.Session(config=None)
        with tf_session.as_default():
            K.set_session(tf_session)
            
            tf_im = tf.placeholder(dtype=HYPER.dtype, shape=((HYPER.B,)+HYPER.image_shape), name='image')
            tf_a_batch = build_image_context(HYPER, tf_im)
            tf_a_list = tf.unstack(tf_a_batch, axis=0)
        
            t_n = tfc.printVars('Trainable Variables', tf.trainable_variables())
            g_n = tfc.printVars('Global Variables', tf.global_variables())
            l_n = tfc.printVars('Local Variables', tf.local_variables())
            assert t_n == g_n
            assert g_n == l_n

            print '\nUninitialized params'
            print tf_session.run(tf.report_uninitialized_variables())
            
            print 'Flushing graph to disk'
            tf_sw = tf.summary.FileWriter(tfc.makeTBDir(HYPER.tb), graph=graph)
            tf_sw.flush()

            print '\n'
            start_time = time.clock()
            for step, b in enumerate(b_it, start=1):
                # if b.epoch > 1 or (params.num_steps >= 0 and step > params.num_steps):
                #     break
                feed_dict = {tf_im:b.im, K.learning_phase(): 0}
                a_list = tf_session.run(tf_a_list, feed_dict = feed_dict)
                assert len(a_list) == len(b.image_name)
                for i, a in enumerate(a_list):
                    ## print 'Writing %s, shape=%s'%(b.image_name[i], a.shape)
                    with open(os.path.join(image_features_folder, os.path.splitext(b.image_name[i])[0] + '.pkl'),
                            'wb') as f:
                        pickle.dump(a, f, pickle.HIGHEST_PROTOCOL)
                if step % 10 == 0:
                    print('Elapsed time for %d steps = %d seconds'%(step, time.clock()-start_time))
            print('Elapsed time for %d steps = %d seconds'%(step, time.clock()-start_time))
            print 'done'
              
def main():
    _data_folder = '../data/generated2'

    parser = arg.ArgumentParser(description='train model')
    parser.add_argument("--num-steps", "-n", dest="num_steps", type=int,
                        help="Number of training steps to run. Defaults to -1 if unspecified, i.e. run to completion",
                        default=-1)
    parser.add_argument("--num-epochs", "-e", dest="num_epochs", type=int,
                        help="Number of training steps to run. Defaults to 10 if unspecified.",
                        default=10)
    parser.add_argument("--batch-size", "-b", dest="batch_size", type=int,
                        help="Batchsize. If unspecified, defaults to the default value in hyper_params",
                        default=None)
    parser.add_argument("--print-steps", "-s", dest="print_steps", type=int,
                        help="Number of training steps after which to log results. Defaults to 10 if unspecified",
                        default=100)
    parser.add_argument("--data-folder", "-d", dest="data_folder", type=str,
                        help="Data folder. If unspecified, defaults to " + _data_folder,
                        default=_data_folder)
    parser.add_argument("--raw-data-folder", dest="raw_data_folder", type=str,
                        help="Raw data folder. If unspecified, defaults to data_folder/training",
                        default=None)
    parser.add_argument("--vgg16-folder", dest="vgg16_folder", type=str,
                        help="vgg16 data folder. If unspecified, defaults to raw_data_folder/vgg16_features",
                        default=None)
    parser.add_argument("--image-folder", dest="image_folder", type=str,
                        help="image folder. If unspecified, defaults to data_folder/formula_images",
                        default=None)
    parser.add_argument("--partial-batch", "-p",  dest="partial_batch", action='store_true',
                        help="Sets assert_whole_batch hyper param to False. Default hyper_param value will be used if unspecified")

    args = parser.parse_args()
    data_folder = args.data_folder
    params = dlc.Properties({'num_steps': args.num_steps, 
                             'print_steps':args.print_steps,
                             'num_epochs': args.num_epochs})
    if args.image_folder:
        params.image_folder = args.image_folder
    else:
        params.image_folder = os.path.join(data_folder,'formula_images')

    if args.raw_data_folder:
        params.raw_data_folder = args.raw_data_folder
    else:
        params.raw_data_folder = os.path.join(data_folder, 'training')

    if args.vgg16_folder:
        params.vgg16_folder = args.vgg16_folder
    else:
        params.vgg16_folder = os.path.join(params.raw_data_folder, 'vgg16_features')
    
    if args.batch_size is not None:
        params.B = args.batch_size
    if args.partial_batch:
        params.assert_whole_batch = False

    run(params)

main()
