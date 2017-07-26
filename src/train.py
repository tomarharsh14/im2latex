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

Created on Tue Jul 25 13:41:32 2017

@author: Sumeet S Singh

Tested on python 2.7
"""
import os
import time
import argparse as arg
import tensorflow as tf
import tf_commons as tfc
from Im2LatexModel import Im2LatexModel
from keras import backend as K
import hyper_params
from data_reader import BatchContextIterator, BatchImageIterator


def train(batch_iterator, HYPER, num_steps=0):
    graph = tf.Graph()
    with graph.as_default():
        model = Im2LatexModel(HYPER)
        train_ops = model.build_train_graph()
        
        total_n = 0
        total_vggnet = 0
        total_init = 0
        total_calstm = 0
        total_output = 0
        total_embedding = 0
        
        print 'Trainable Variables'
        for var in tf.trainable_variables():
            n = tfc.sizeofVar(var)
            total_n += n
            if var.name.startswith('VGGNet/'):
                total_vggnet += n
            elif 'CALSTM' in var.name:
                total_calstm += n
            elif var.name.startswith('Im2LatexRNN/Output_Layer/'):
                total_output += n
            elif var.name.startswith('Initializer_MLP/'):
                total_init += n
            elif var.name.startswith('Im2LatexRNN/Ey/Embedding_Matrix'):
                total_embedding += n
            else:
                assert False
            print var.name, K.int_shape(var), 'num_params = ', n
            
        print '\nTotal number of trainable params = ', total_n
        print 'Convnet: %d (%d%%)'%(total_vggnet, total_vggnet*100./total_n)
        print 'Initializer: %d (%d%%)'%(total_init, total_init*100./total_n)
        print 'CALSTM: %d (%d%%)'%(total_calstm, total_calstm*100./total_n)
        print 'Output Layer: %d (%d%%)'%(total_output, total_output*100./total_n)
        print 'Embedding Matrix: %d (%d%%)'%(total_embedding, total_embedding*100./total_n)

#        print '\nTrainable Variables Initializers'
#        for var in tf.trainable_variables():
#            print var.initial_value
            
        config=tf.ConfigProto(log_device_placement=True)
        config.gpu_options.allow_growth = True

        with tf.Session(config=config) as session:
            print 'Flushing graph to disk'
            tf_sw = tf.summary.FileWriter(tfc.makeTBDir(HYPER.tb), graph=graph)
            tf_sw.flush()
            tf.global_variables_initializer().run()
        
            if batch_iterator is None or num_steps == 0:
                return

            start_time = time.clock()
            for b in batch_iterator:
                feed = {train_ops.y_s: b.y_s, train_ops.seq_lens: b.seq_len, train_ops.im: b.im}
                session.run(train_ops.train, feed_dict=feed)
                if (num_steps >= 0) and (b.step >= num_steps):
                    break
                if b.step % 10 == 0:
                    print 'Elapsed time for %d steps = %f'%(b.step, time.clock()-start_time)
            print 'Elapsed time for %d steps = %f'%(b.step, time.clock()-start_time)

def main():
    data_folder = '../data/generated2'
    HYPER = hyper_params.make_hyper({'B':1, 'build_image_context':False})

    parser = arg.ArgumentParser(description='train model')
    parser.add_argument("--num_steps", "-n", dest="num_steps", type=int,
                        help="Number of training steps to run. Defaults to -1 if unspecified, i.e. run to completion", 
                        default=-1)
    parser.add_argument("--batch_size", "-b", dest="batch_size", type=int,
                        help="Batchsize. If unspecified, defaults to whatever is in hyper_params", 
                        default=HYPER.B)
    parser.add_argument("--data_folder", "-d", dest="data_folder", type=str,
                        help="Data folder. If unspecified, defaults " + data_folder, 
                        default=data_folder)
    
    args = parser.parse_args()
    image_folder = os.path.join(data_folder,'formula_images')
#    raw_data_folder = os.path.join(data_folder, 'training')
    raw_data_folder = os.path.join(data_folder, 'training', 'temp_dir')
    vgg16_folder = os.path.join(data_folder, 'training', 'vgg16_features')

    b_it = BatchContextIterator(raw_data_folder, vgg16_folder, HYPER)
    train(b_it, HYPER, args.num_steps)
    
main()