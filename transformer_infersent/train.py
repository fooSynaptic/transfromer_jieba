# -*- coding: utf-8 -*-
#/usr/bin/python3

import tensorflow as tf

from hyperparams import infersent_Block_Hyperparams as hp
from data_load import get_batch_data, load_vocabs
from modules import *
import os, codecs
from tqdm import tqdm


class Graph():
    def __init__(self, is_training=True):
        self.graph = tf.Graph()
        with self.graph.as_default():
            if is_training:
                self.x1, self.x2, self.y, self.num_batch = get_batch_data() 
                #self.x, self.label, self.num_batch = get_batch_data() # (N, T)
                #self.y = tf.one_hot(self.label, depth = hp.n_class)
            else: # inference
                self.x1 = tf.placeholder(tf.int32, shape=(None, hp.maxlen))
                self.x2 = tf.placeholder(tf.int32, shape = (None, hp.maxlen))
                #self.label = tf.placeholder(tf.int32, shape = (None, hp.n_class))
                #self.y = tf.placeholder(tf.int32, shape = (None, hp.n_class))
                #self.y = tf.placeholder(tf.int32, shape=(None, hp.maxlen))

            # define decoder inputs
            #for sentence relationship learning task we want to encoder sent1 to e1, then decoder(e1 + sent2)
            #to get a more sementic relationship across corpus
            self.decoder_inputs = tf.concat((tf.ones_like(self.x2[:, :1])*2, self.x2[:, :-1]), -1) # 2:<S>

            # Load vocabulary    
            word2idx, idx2word = load_vocabs()

            
            # Encoder
            with tf.variable_scope("encoder"):
                ## Embedding
                self.enc = embedding(self.x1, 
                                      vocab_size=len(word2idx), 
                                      num_units=hp.hidden_units, 
                                      scale=True,
                                      scope="enc_embed")
                
                ## Positional Encoding
                if hp.sinusoid:
                    self.enc += positional_encoding(self.x1,
                                      num_units=hp.hidden_units, 
                                      zero_pad=False, 
                                      scale=False,
                                      scope="enc_pe")
                else:
                    self.enc += embedding(tf.tile(tf.expand_dims(tf.range(tf.shape(self.x1)[1]), 0), [tf.shape(self.x1)[0], 1]),
                                      vocab_size=hp.maxlen, 
                                      num_units=hp.hidden_units, 
                                      zero_pad=False, 
                                      scale=False,
                                      scope="enc_pe")
                    
                 
                ## Dropout
                self.enc = tf.layers.dropout(self.enc, 
                                            rate=hp.dropout_rate, 
                                            training=tf.convert_to_tensor(is_training))
                
                ## Blocks
                for i in range(hp.num_blocks):
                    with tf.variable_scope("num_blocks_{}".format(i)):
                        ### Multihead Attention
                        self.enc = multihead_attention(queries=self.enc, 
                                                        keys=self.enc, 
                                                        num_units=hp.hidden_units, 
                                                        num_heads=hp.num_heads, 
                                                        dropout_rate=hp.dropout_rate,
                                                        is_training=is_training,
                                                        causality=False)
                        
                        ### Feed Forward
                        self.enc = feedforward(self.enc, num_units=[4*hp.hidden_units, hp.hidden_units])
            
            
            #for sentence relationship learning task we want to encoder sent1 to e1, then decoder(e1 + sent2)
            #to get a more sementic relationship across corpus

            # Decoder
            with tf.variable_scope("decoder"):
                ## Embedding
                self.dec = embedding(self.decoder_inputs, 
                                      vocab_size=len(word2idx), 
                                      num_units=hp.hidden_units,
                                      scale=True, 
                                      scope="dec_embed")
                
                ## Positional Encoding
                if hp.sinusoid:
                    self.dec += positional_encoding(self.decoder_inputs,
                                      vocab_size=hp.maxlen, 
                                      num_units=hp.hidden_units, 
                                      zero_pad=False, 
                                      scale=False,
                                      scope="dec_pe")
                else:
                    self.dec += embedding(tf.tile(tf.expand_dims(tf.range(tf.shape(self.decoder_inputs)[1]), 0), [tf.shape(self.decoder_inputs)[0], 1]),
                                      vocab_size=hp.maxlen, 
                                      num_units=hp.hidden_units, 
                                      zero_pad=False, 
                                      scale=False,
                                      scope="dec_pe")
                
                ## Dropout
                self.dec = tf.layers.dropout(self.dec, 
                                            rate=hp.dropout_rate, 
                                            training=tf.convert_to_tensor(is_training))
                
                ## Blocks
                for i in range(hp.num_blocks):
                    with tf.variable_scope("num_blocks_{}".format(i)):
                        ## Multihead Attention ( self-attention)
                        self.dec = multihead_attention(queries=self.dec, 
                                                        keys=self.dec, 
                                                        num_units=hp.hidden_units, 
                                                        num_heads=hp.num_heads, 
                                                        dropout_rate=hp.dropout_rate,
                                                        is_training=is_training,
                                                        causality=True, 
                                                        scope="self_attention")
                        
                        ## Multihead Attention ( vanilla attention)
                        self.dec = multihead_attention(queries=self.dec, 
                                                        keys=self.enc, 
                                                        num_units=hp.hidden_units, 
                                                        num_heads=hp.num_heads,
                                                        dropout_rate=hp.dropout_rate,
                                                        is_training=is_training, 
                                                        causality=False,
                                                        scope="vanilla_attention")
                        
                        ## Feed Forward
                        self.dec = feedforward(self.dec, num_units=[4*hp.hidden_units, hp.hidden_units])
            

            # Final linear projection
            '''
            #print(self.enc.shape) #4, 500, 512
            self.enc = tf.reduce_sum(self.enc, axis=2) #4, 500
            self.enc = tf.layers.batch_normalization(self.enc, True)
            self.logits = tf.layers.dense(self.enc, hp.n_class) #4, 2
            #print(self.logits.shape)
            self.preds = tf.to_int32(tf.arg_max(self.logits, dimension=-1))
            '''
            self.dec = tf.reduce_sum(self.dec, axis=2)
            self.dec = tf.layers.batch_normalization(self.dec, True)
            self.logits = tf.layers.dense(self.dec, len(hp.relations))
            self.preds = tf.to_int32(tf.arg_max(self.logits, dimension = -1))

                
            if is_training:  
                self.y_hotting = tf.one_hot(self.y, depth = len(hp.relations))

                #Accuracy
                self.cpl = tf.equal(tf.convert_to_tensor(self.y, tf.int32), self.preds)
                self.cpl = tf.to_int32(self.cpl)
                self.acc = tf.reduce_sum(self.cpl) / tf.to_int32(tf.reduce_sum(self.y_hotting))
                tf.summary.scalar('acc', self.acc)

                # Loss
                self.y_smoothed = label_smoothing(self.y_hotting)
                self.loss = tf.nn.softmax_cross_entropy_with_logits(logits=self.logits, labels=self.y_smoothed)
                self.mean_loss = tf.reduce_sum(self.loss)/tf.reduce_sum(self.y_hotting)
                #self.mean_loss = tf.reduce_sum(self.loss*self.istarget) / (tf.reduce_sum(self.istarget))
                

                # Training Scheme
                self.global_step = tf.Variable(0, name='global_step', trainable=False)
                self.optimizer = tf.train.AdamOptimizer(learning_rate=hp.lr, beta1=0.9, beta2=0.98, epsilon=1e-8)
                self.train_op = self.optimizer.minimize(self.mean_loss, global_step=self.global_step)
                   
                # Summary 
                tf.summary.scalar('mean_loss', self.mean_loss)
                self.merged = tf.summary.merge_all()


if __name__ == '__main__':                
    # Load vocabulary    
    word2idx, idx2word = load_vocabs()
    
    # Construct graph
    g = Graph("train"); print("Graph loaded")
    
    # Start session
    sv = tf.train.Supervisor(graph=g.graph, 
                             logdir=hp.logdir,
                             save_model_secs=0)
    with sv.managed_session() as sess:
        for epoch in range(1, hp.num_epochs+1): 
            if sv.should_stop(): break
            for step in tqdm(range(g.num_batch), total=g.num_batch, ncols=70, leave=False, unit='b'):
                sess.run(g.train_op)
                
            gs = sess.run(g.global_step)   
            sv.saver.save(sess, hp.logdir + '/model_epoch_%02d_gs_%d' % (epoch, gs))
    
    print("Done")    
    
