import argparse
import os
import time
import random
# from baselines.common.schedules import LinearSchedule

import numpy as np
import tensorflow as tf


import tensorlayer as tl
from WebSimEnv2 import WebSimEnv

parser = argparse.ArgumentParser(description='Train or test neural net motor controller.')
parser.add_argument('--train', dest='train', action='store_true', default=True)
parser.add_argument('--test', dest='test', action='store_false')
args = parser.parse_args()

#####################  hyper parameters  ####################

class LinearSchedule(object):
    def __init__(self, schedule_timesteps, final_p, initial_p=1.0):
        """Linear interpolation between initial_p and final_p over
        schedule_timesteps. After this many timesteps pass final_p is
        returned.

        Parameters
        ----------
        schedule_timesteps: int
            Number of timesteps for which to linearly anneal initial_p
            to final_p
        initial_p: float
            initial output value
        final_p: float
            final output value
        """
        self.schedule_timesteps = schedule_timesteps
        self.final_p = final_p
        self.initial_p = initial_p

    def value(self, t):
        """See Schedule.value"""
        fraction = min(float(t) / self.schedule_timesteps, 1.0)
        return self.initial_p + fraction * (self.final_p - self.initial_p)

RANDOMSEED = 1  # random seed

LR_A = 0.01  # learning rate for actor
LR_C = 0.02  # learning rate for critic
GAMMA = 0.99 # reward discount
TAU = 0.01  # soft replacement
MEMORY_CAPACITY = 10000  # size of replay buffer
BATCH_SIZE = 32  # update batchsize

MAX_EPISODES = 10  # total number of episodes for training
MAX_EP_STEPS = 288  # total number of steps for each episode
VAR = 2 #标准差
SA = 1 #指导周期数
guidpfrom = 0.5
guidpto = 0.05
actionexploration = LinearSchedule(schedule_timesteps=6,
                                            initial_p=guidpfrom,
                                            final_p=guidpto)

###############################  DDPG  ####################################


class DDPG(object):

    def __init__(self, a_dim, s_dim, a_bound):
        # memory用于储存跑的数据的数组：
        # 保存个数MEMORY_CAPACITY，s_dim * 2 + a_dim + 1：分别是两个state，一个action，和一个reward
        self.memory = np.zeros((MEMORY_CAPACITY, s_dim * 2 + a_dim + 1), dtype=np.float32)
        self.pointer = 0
        self.count = 0
        self.a_dim, self.s_dim, self.a_bound = a_dim, s_dim, a_bound

        W_init = tf.random_normal_initializer(mean=0, stddev=0.3)
        b_init = tf.constant_initializer(0.1)

        # 建立actor网络，输入s，输出a
        def get_actor(input_state_shape, name=''):
            """
            Build actor network
            :param input_state_shape: state
            :param name: name
            :return: act
            """
            # def fx1(x):
            #     c = Categorical(x)
            #     act = c.sample().numpy()
            #     return act.tolist()

            inputs = tl.layers.Input(input_state_shape, name='A_input')
            x = tl.layers.Dense(n_units=64, act=tf.nn.relu, W_init=W_init, b_init=b_init, name='A_l1')(inputs)
            x = tl.layers.Dense(n_units=64, act=tf.nn.relu, W_init=W_init, b_init=b_init, name='A_l2')(x)
            x = tl.layers.Dense(n_units=a_dim, act=tf.nn.sigmoid, W_init=W_init, b_init=b_init, name='A_a')(x)
            x = tl.layers.Lambda(lambda x: (np.array(a_bound)*x))(x)
            # x = tl.layers.Dense(n_units=a_dim,act = tf.nn.softmax)(x)
            return tl.models.Model(inputs=inputs, outputs=x, name='Actor' + name)


        # 建立Critic网络，输入s，a。输出Q值
        def get_critic(input_state_shape, input_action_shape, name=''):
            """
            Build critic network
            :param input_state_shape: state
            :param input_action_shape: act
            :param name: name
            :return: Q value Q(s,a)
            """
            s = tl.layers.Input(input_state_shape, name='C_s_input')
            a = tl.layers.Input(input_action_shape, name='C_a_input')
            x = tl.layers.Concat(1)([s, a])
            x = tl.layers.Dense(n_units=64, act=tf.nn.relu, W_init=W_init, b_init=b_init, name='C_l1')(x)
            x = tl.layers.Dense(n_units=64, act=tf.nn.relu, W_init=W_init, b_init=b_init, name='C_l2')(x)
            x = tl.layers.Dense(n_units=1, W_init=W_init, b_init=b_init, name='C_out')(x)
            return tl.models.Model(inputs=[s, a], outputs=x, name='Critic' + name)

        self.actor = get_actor([None, s_dim])
        self.critic = get_critic([None, s_dim], [None, a_dim])
        self.actor.train()
        self.critic.train()

        # 更新参数，只用于首次赋值，之后就没用了
        def copy_para(from_model, to_model):
            """
            Copy parameters for soft updating
            :param from_model: latest model
            :param to_model: target model
            :return: None
            """
            for i, j in zip(from_model.trainable_weights, to_model.trainable_weights):
                j.assign(i)

        # 建立actor_target网络，并和actor参数一致，不能训练
        self.actor_target = get_actor([None, s_dim], name='_target')
        copy_para(self.actor, self.actor_target)
        self.actor_target.eval()

        # 建立critic_target网络，并和actor参数一致，不能训练
        self.critic_target = get_critic([None, s_dim], [None, a_dim], name='_target')
        copy_para(self.critic, self.critic_target)
        self.critic_target.eval()

        self.R = tl.layers.Input([None, 1], tf.float32, 'r')

        # 建立ema，滑动平均值
        self.ema = tf.train.ExponentialMovingAverage(decay=1 - TAU)  # soft replacement

        self.actor_opt = tf.optimizers.Adam(LR_A)
        self.critic_opt = tf.optimizers.Adam(LR_C)

    def ema_update(self):
        """
        滑动平均更新
        """
        # 其实和之前的硬更新类似，不过在更新赋值之前，用一个ema.average。
        paras = self.actor.trainable_weights + self.critic.trainable_weights  # 获取要更新的参数包括actor和critic的
        self.ema.apply(paras)  # 主要是建立影子参数
        for i, j in zip(self.actor_target.trainable_weights + self.critic_target.trainable_weights, paras):
            i.assign(self.ema.average(j))  # 用滑动平均赋值

    # 选择动作，把s带进入，输出a
    def choose_action(self, s):
        """
        Choose action
        :param s: state
        :return: act
        """
        return self.actor(np.array([s], dtype=np.float32))[0]

    # def select_action(self, a): #用来选择在输出概率里最大的动作
    #     c = a.numpy()
    #     lst = list(map(float, c))
    #     t = max(lst)
    #     action = lst.index(t)
    #     return action



    def learn(self):
        """
        Update parameters
        :return: None
        """
        indices = np.random.choice(self.count, size=BATCH_SIZE)  # 随机BATCH_SIZE个随机数
        bt = self.memory[indices, :]  # 根据indices，选取数据bt，相当于随机
        # print("bt",bt)
        bs = bt[:, :self.s_dim]  # 从bt获得数据s
        ba = bt[:, self.s_dim:self.s_dim + self.a_dim]  # 从bt获得数据a
        br = bt[:, -self.s_dim - 1:-self.s_dim]  # 从bt获得数据r
        bs_ = bt[:, -self.s_dim:]  # 从bt获得数据s'

        # Critic：
        # Critic更新和DQN很像，不过target不是argmax了，是用critic_target计算出来的。
        # br + GAMMA * q_
        with tf.GradientTape() as tape:
            # a_ = self.actor_target(bs_)
            # q_ = self.critic_target([bs_, a_])
            y = br
            # y = br + GAMMA * q_
            q = self.critic([bs, ba])
            # print("q",q,"y",y)

            td_error = tf.losses.mean_squared_error(y, q)
            # print("td_error",np.average(td_error))
        c_grads = tape.gradient(td_error, self.critic.trainable_weights)
        self.critic_opt.apply_gradients(zip(c_grads, self.critic.trainable_weights))

        # Actor：
        # Actor的目标就是获取最多Q值的。
        with tf.GradientTape() as tape:
            a = self.actor(bs)
            q = self.critic([bs, a])
            a_loss = -tf.reduce_mean(q)  # 【敲黑板】：注意这里用负号，是梯度上升！也就是离目标会越来越远的，就是越来越大。
        a_grads = tape.gradient(a_loss, self.actor.trainable_weights)
        self.actor_opt.apply_gradients(zip(a_grads, self.actor.trainable_weights))

        self.ema_update()

    # 保存s，a，r，s_
    def store_transition(self, s, a, r, s_):
        """
        Store data in data buffer
        :param s: state
        :param a: act
        :param r: reward
        :param s_: next state
        :return: None
        """
        # 整理s，s_,方便直接输入网络计算
        s = s.astype(np.float32)
        s_ = s_.astype(np.float32)

        # 把s, a, [r], s_横向堆叠
        transition = np.hstack((s, a, [r], s_))

        # pointer是记录了曾经有多少数据进来。
        # index是记录当前最新进来的数据位置。
        # 所以是一个循环，当MEMORY_CAPACITY满了以后，index就重新在最底开始了
        index = self.pointer % MEMORY_CAPACITY  # replace the old memory with new memory
        # 把transition，也就是s, a, [r], s_存进去。
        self.memory[index, :] = transition
        self.pointer += 1
        self.count +=1
        if self.count > MEMORY_CAPACITY:
            self.count = MEMORY_CAPACITY

    def save_ckpt(self):
        """
        save trained weights
        :return: None
        """
        if not os.path.exists('model6'):
            os.makedirs('model6')

        tl.files.save_weights_to_hdf5('model6/ddpg_actor.hdf5', self.actor)
        tl.files.save_weights_to_hdf5('model6/ddpg_actor_target.hdf5', self.actor_target)
        tl.files.save_weights_to_hdf5('model6/ddpg_critic.hdf5', self.critic)
        tl.files.save_weights_to_hdf5('model6/ddpg_critic_target.hdf5', self.critic_target)

    def load_ckpt(self):
        """
        load trained weights
        :return: None
        """
        tl.files.load_hdf5_to_weights_in_order('model6/ddpg_actor.hdf5', self.actor)
        tl.files.load_hdf5_to_weights_in_order('model6/ddpg_actor_target.hdf5', self.actor_target)
        tl.files.load_hdf5_to_weights_in_order('model6/ddpg_critic.hdf5', self.critic)
        tl.files.load_hdf5_to_weights_in_order('model6/ddpg_critic_target.hdf5', self.critic_target)




if __name__ == '__main__':

    # 初始化环境
    jarpath = os.path.abspath('.') + '\WebSimulator2.16.jar'
    env = WebSimEnv(runspace="D:\\Compiler\\for_PYCharm\\Runspace\\",
                    tracepath="D:\\Compiler\\for_PYCharm\\Runspace\\tracedata\\",
                    jarpath=jarpath,
                    Djavapath='',
                    trashpath='',
                    requestrate=0.01)

    # reproducible，设置随机种子，为了能够重现
    env.seed(RANDOMSEED)
    np.random.seed(RANDOMSEED)
    tf.random.set_seed(RANDOMSEED)

    # 定义状态空间，动作空间，动作幅度范围
    s_dim = env.observation_space.shape[0]
    a_dim = env.action_space.n
    a_bound = 14
    # 用DDPG算法
    ddpg = DDPG(a_dim, s_dim, a_bound)

    # guide_step = 0
    # guide_flag = False
    # guide_prob = 0
    # start_prob = 0.10
    # 训练部分：
    if args.train:  # train

        reward_buffer = []  # 用于记录每个EP的reward，统计变化
        t0 = time.time()  # 统计时间
        for i in range(MAX_EPISODES):
            t1 = time.time()
            state = env.reset()
            # guide_flag = False
            # guide_step = 0
            ep_reward = 0  # 记录当前EP的reward
            for j in range(MAX_EP_STEPS):
                # Add exploration noise
                print("i_episode",i)
                print("i_step",j)

                # if j < 30 and not guide_flag:
                #     random_prob = random.uniform(0, 1)
                #     if random_prob < start_prob-(start_prob/(30*288))*(i+1)*j:
                #         guide_flag = True

                if i < SA:
                    print('选取指导动作：')
                    pro = env.getsuggestedaction(a_bound)[0]
                    action = np.array(pro)
                    print("action",pro,type(action))
                    # guide_step = guide_step + 1
                    # if guide_step == 30:
                    #     guide_step = 0
                    #     guide_flag = False
                else:
                    print('输出训练动作：')
                    action = ddpg.choose_action(state)
                    act_pro = actionexploration.value(int(i))
                    random_prob = random.uniform(0, 1)
                    if random_prob < act_pro:
                        print("采用概率分布：",act_pro,"原有action",action)
                        action = np.clip(np.random.uniform(-2,2)+action,0,14)
                    else:
                        print("动作输出：")
                        action = action.numpy()

                    pro = action.tolist()[0]
                    print('action', pro,type(action))

                # pro_a = ddpg.choose_action(state)  # 这里很简单，直接用actor估算出a动作
                # print("pro_a",pro_a)
                # action = ddpg.select_action(pro_a).tolist() #用来放入模拟平台选取动作
                # print("action",action)
                # action = ddpg.choose_action(state)
                # # # 为了能保持开发，这里用了另外一种方式增加探索。
                # # # 因此需要需要以a为均值，VAR为标准差，建立正态分布，再从正态分布采样出a
                # # # 因为a是均值，所以a的概率是最大的。但a相对其他概率由多大，是靠VAR调整。这里我们其实可以增加更新VAR，动态调整a的确定性
                # action = np.clip(np.random.normal(action, VAR), -4, 4)
                # print("action",action,type(action))
                # # # 与环境进行互动
                #
                # # act = ddpg.choose_action(state)
                # # acti = act.numpy()[0]*10
                # # action = round(acti)
                # pro = action.tolist()[0]
                # print("action",pro,type(pro))

                next_state, reward, done, _ = env.step(pro)

                # 保存s，a，r，s_
                ddpg.store_transition(state, action , reward, next_state)

                # 第一次数据满了，就可以开始学习
                if ddpg.pointer > BATCH_SIZE:
                    for k in range(10):
                        ddpg.learn()

                # 输出数据记录
                state = next_state
                ep_reward += reward  # 记录当前EP的总reward

            reward_buffer.append(ep_reward)
            print("////////////////////////////////")
            doc = open('out.txt', 'a')
            print("/////////////////////////////////////////////", file=doc)
            print(reward_buffer, file=doc)
            doc.close()

        ddpg.save_ckpt()

    # test
    # ddpg.load_ckpt()
    # while True:
    #     state = env.reset()
    #     for i in range(MAX_EP_STEPS):
    #         action = ddpg.choose_action(state).numpy()
    #         pro = action.tolist()[0]
    #         print("action", pro)
    #         next_state, reward, done, _ = env.step(pro)
    #         if done:
    #             break