import os
import numpy as np
import tensorflow as tf
# from tensorflow.python.keras import backend as K
from tensorflow.python.keras.models import Model
from tensorflow.python.keras.layers import Input, Flatten, Dense, Activation,\
    concatenate, Conv2D, GlobalAveragePooling2D, BatchNormalization
from . import settings


class DeepQNetwork(object):
    def __init__(self, load_network=False):
        self.main_input, self.q_values, self.model = self.build_q_network()

        if not os.path.exists(settings.SAVE_NETWORK_PATH):
            os.makedirs(settings.SAVE_NETWORK_PATH)
        self.saver = tf.train.Saver(self.model.trainable_weights)
        self.sess = tf.InteractiveSession()
        self.sess.run(tf.global_variables_initializer())

        if load_network:
            self.load_network()

    def build_q_network(self):
        main_input = Input(shape=settings.INPUT_SHAPE, dtype='float32')
        x = Conv2D(16, (3, 3), activation='relu', name='conv_1')(main_input)
        x = Conv2D(4, (3, 3), activation='relu', name='conv_2')(x)
        x = Conv2D(4, (5, 5), activation='relu', name='conv_3')(x)
        x = Conv2D(1, (5, 5), name='main/q_value')(x)
        q_values = Flatten()(x)
        model = Model(inputs=main_input, outputs=q_values)

        return main_input, q_values, model


    def load_network(self):
        checkpoint = tf.train.get_checkpoint_state(settings.SAVE_NETWORK_PATH)
        if checkpoint and checkpoint.model_checkpoint_path:
            self.saver.restore(self.sess, checkpoint.model_checkpoint_path)
            print('Successfully loaded: ' + checkpoint.model_checkpoint_path)
        else:
            print('Loading failed')


    def compute_q_values(self, s):
        return self.q_values.eval(
            feed_dict={
                self.main_input: np.array(s, dtype=np.float32).transpose((0, 3, 2, 1)),
                # self.local_input: np.array(local_features, dtype=np.float32)
                # K.learning_phase(): 0
            })[:, 0]

    def get_action(self, s):
        return np.argmax(self.compute_q_values(s))


class FittingDeepQNetwork(DeepQNetwork):

    def __init__(self, load_network=False):
        super(FittingDeepQNetwork, self).__init__(load_network=False)

        model_weights = self.model.trainable_weights
        # Create target network
        self.target_main_input, self.target_q_values, self.target_model = self.build_q_network()
        target_model_weights = self.target_model.trainable_weights

        # Define target network update operation
        self.update_target_network = [target_model_weights[i].assign(model_weights[i]) for i in
                                      range(len(target_model_weights))]

        # Define loss and gradient update operation
        self.a, self.y, self.loss, self.grad_update = self.build_training_op(model_weights)
        self.sess.run(tf.global_variables_initializer())

        if load_network:
            self.load_network()
        # Initialize target network
        self.sess.run(self.update_target_network)

        self.n_steps = 0
        self.epsilon = settings.INITIAL_EPSILON
        self.epsilon_step = (settings.FINAL_EPSILON - settings.INITIAL_EPSILON) / settings.EXPLORATION_STEPS


        for var in model_weights:
            tf.summary.histogram(var.name, var)
        self.summary_placeholders, self.update_ops, self.summary_op = self.setup_summary()
        self.summary_writer = tf.summary.FileWriter(settings.SAVE_SUMMARY_PATH, self.sess.graph)


    def get_action(self, s):
        # e-greedy exploration
        if self.epsilon > np.random.random():
            # if 0.5 > np.random.random():
            #     return get_default_action(s, local_features)
            return np.random.randint((settings.MAX_MOVE * 2 + 1) ** 2)
        else:
            return super(FittingDeepQNetwork, self).get_action(s)



    def get_fingerprint(self):
        return self.n_steps, self.epsilon

    def compute_target_q_values(self, s):
        return self.target_q_values.eval(
            feed_dict={
                self.target_main_input: np.array(s, dtype=np.float32).transpose((0, 3, 2, 1)),
                # self.target_local_input: np.array(local_features, dtype=np.float32)
                # K.learning_phase(): 0
            })[:, 0]

    def fit(self, s_batch, a_batch, y_batch):
        loss, _ = self.sess.run([self.loss, self.grad_update], feed_dict={
            self.main_input: np.array(s_batch, dtype=np.float32).transpose((0, 3, 2, 1)),
            self.a: np.array(a_batch, dtype=np.float32),
            # self.local_input: np.array(local_batch, dtype=np.float32),
            # K.learning_phase(): 1,
            self.y: np.array(y_batch, dtype=np.float32)
        })
        return loss

    def run_cyclic_updates(self):
        self.n_steps += 1
        # Update target network
        if self.n_steps % settings.TARGET_UPDATE_INTERVAL == 0:
            self.sess.run(self.update_target_network)
            print("Update target network")

        # Save network
        if self.n_steps % settings.SAVE_INTERVAL == 0:
            save_path = self.saver.save(self.sess, settings.SAVE_NETWORK_PATH, global_step=(self.n_steps))
            print('Successfully saved: ' + save_path)

        # Anneal epsilon linearly over time
        if self.n_steps < settings.EXPLORATION_STEPS:
            self.epsilon += self.epsilon_step


    def build_training_op(self, q_network_weights):
        a = tf.placeholder(tf.int64, [None])
        y = tf.placeholder(tf.float32, shape=(None))

        # Convert action to one hot vector
        a_one_hot = tf.one_hot(a, (settings.MAX_MOVE * 2 + 1) ** 2, 1.0, 0.0)
        q_value = tf.reduce_sum(tf.mul(self.q_values, a_one_hot), reduction_indices=1)
        # q_value = tf.reduce_sum(self.q_values, reduction_indices=1)
        loss = tf.losses.huber_loss(y, q_value)
        optimizer = tf.train.RMSPropOptimizer(settings.LEARNING_RATE, momentum=settings.MOMENTUM, epsilon=settings.MIN_GRAD)
        grad_update = optimizer.minimize(loss, var_list=q_network_weights)

        return a, y, loss, grad_update

    def setup_summary(self):
        avg_max_q = tf.Variable(0.)
        tf.summary.scalar('Average_Max_Q', avg_max_q)
        avg_loss = tf.Variable(0.)
        tf.summary.scalar('Average_Loss', avg_loss)
        summary_vars = [avg_max_q, avg_loss]
        summary_placeholders = [tf.placeholder(tf.float32) for _ in range(len(summary_vars))]
        update_ops = [summary_vars[i].assign(summary_placeholders[i]) for i in range(len(summary_vars))]
        summary_op = tf.summary.merge_all()
        return summary_placeholders, update_ops, summary_op

    def write_summary(self, avg_loss, avg_q_max):
        stats = [avg_q_max, avg_loss]
        for i in range(len(stats)):
            self.sess.run(self.update_ops[i], feed_dict={
                self.summary_placeholders[i]: float(stats[i])
            })
        summary_str = self.sess.run(self.summary_op)
        self.summary_writer.add_summary(summary_str, self.n_steps)
