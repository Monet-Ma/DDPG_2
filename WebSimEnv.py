# coding: utf-8

# In[ ]:


import jpype
import numpy as np
from gym import spaces
from gym.utils import seeding
from jpype import *


# class WebSimEnv(gym.Env):
class WebSimEnv:
    """
    Description:
        A simulation of web application
    Source:
        This environment corresponds to the version of the cart-pole problem described by Barto, Sutton, and Anderson

    Observation: 
        Definition of States
        1.request rate
        2.averagedelay
        3.hour in week
        4.<mips,number,isondemand,price>,<mips,number,isondemand,price>,<mips,number,isondemand,price>

    Actions:
       (VMID1 Vmnum1,VMID2 Vmnum2,VMID3 Vmnum3)
       0 do nothing
       1 Vm1 +10%, 
       2 Vm1 -10%
       3 Vm2 +10%, 
       4 Vm2 -10%
       5 Vm3 +10%, 
       6 Vm3 -10%
       
    Rewards:
        -(Average delay* panaltyfactor+AverageRentalcost* factor)

    Starting State:
       

    Episode Termination:
       reach a given time
    
    metadata = {
        'render.modes': ['human', 'rgb_array'],
        'video.frames_per_second' : 50
    }
    """

    def __init__(self, runspace, tracepath, jarpath, Djavapath, trashpath, requestrate):
        """self.gravity = 9.8
        self.masscart = 1.0
        self.masspole = 0.1
        self.total_mass = (self.masspole + self.masscart)
        self.length = 0.5 # actually half the pole's length
        self.polemass_length = (self.masspole * self.length)
        self.force_mag = 10.0
        self.tau = 0.02  # seconds between state updates
        self.kinematics_integrator = 'euler'
        
        # Angle at which to fail the episode
        self.theta_threshold_radians = 12 * 2 * math.pi / 360
        self.x_threshold = 2.4

        # Angle limit set to 2 * theta_threshold_radians so failing observation is still within bounds
        high = np.array([
            self.x_threshold * 2,
            np.finfo(np.float32).max,
            self.theta_threshold_radians * 2,
            np.finfo(np.float32).max])

        self.action_space = spaces.Discrete(2)
        self.observation_space = spaces.Box(-high, high, dtype=np.float32)

        self.seed()
        self.viewer = None
        self.state = None

        self.steps_beyond_done = None
        
        spaces.Box(low=0, high=255, shape=(STATE_H, STATE_W, 3), dtype=np.uint8)
         high = np.array([np.inf]*24)
        self.action_space = spaces.Box(np.array([-1,-1,-1,-1]), np.array([+1,+1,+1,+1]))
        self.observation_space = spaces.Box(-high, high)
        """
        self.threadnum = 1

        startJVM(getDefaultJVMPath(), "-ea", "-Djava.class.path=%s" % (jarpath), "-Djava.ext.dirs=%s" % Djavapath,convertStrings=False)
        # startJVM(getDefaultJVMPath(),"-ea", "-Djava.class.path=%s" % ('/home/cloud/JavaJar/WebSim.jar'),"-Djava.ext.dirs=%s" %'/home/cloud/R/x86_64-pc-linux-gnu-library/3.4/rJava/jri/:/usr/lib/R/lib:/usr/lib/R/bin:/home/cloud/JavaJar/lib')
        JDClass = JClass("org.webapplication.Totaldelegate")
        # self.jd = JDClass()
        system = JClass('java.lang.System')
        value = system.getProperty(str("java.class.path"))
        print(value)
        # self.jd = JDClass("/home/cloud/Runspace",3600,"2016-06-18T011:00:00",200,6,0.05)
        self.jd = JDClass(self.threadnum, runspace, tracepath, 60, "2016-06-18T011:00:00", 300, 4, requestrate, 5, trashpath, 1, False)
        self.steps_beyond_done = 1;

        # vmtype_count = self.jd.getvmtypes()
        # print("vmtype_count=", vmtype_count)
        # self.action_space = spaces.Discrete(vmtype_count * 2 + 1)
        #
        # high = [np.finfo(np.float32).max, np.finfo(np.float32).max]
        # low = [0, 0]
        # for i in range(vmtype_count):
        #     high += [np.finfo(np.float32).max, np.finfo(np.float32).max]
        #     low += [0, 0]
        # high = np.array(high)
        # low = np.array(low)
        # self.observation_space = spaces.Box(low, high)
        # self.statelength = vmtype_count * 2 + 3

        self.action_space = spaces.Discrete(1)
        # chaofan revised
        # high = [np.finfo(np.float32).max, np.finfo(np.float32).max, np.finfo(np.float32).max]
        # low = [0,0,0]
        high = [np.finfo(np.float32).max, np.finfo(np.float32).max]
        low = [0,0]
        o_high = np.array(high)
        o_low = np.array(low)
        self.observation_space = spaces.Box(o_low, o_high)
        self.statelength = 3 + 1;

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def getsuggestedaction(self,bound):
        suggestedaction = self.jd.getsactions(jpype.java.lang.Integer(bound))
        return suggestedaction


    # def getsuggestedaction(self, action_space):
    #     # 2020/08/16 yipei revised 添加了参数action_space
    #     suggestedactions = self.jd.getsactions(jpype.java.lang.Integer(action_space))
    #     return suggestedactions

    def step(self, action):

        actionslist = jpype.java.util.ArrayList()

        actionslist.add(jpype.java.lang.Float(action))

        observations = np.array(self.jd.step(actionslist))
        self.state = observations[0:-1]
        reward = observations[-1]
        self.steps_beyond_done += 1
        # if self.steps_beyond_done>=3024:
        if self.steps_beyond_done >= 288:
            done = 1
        else:
            done = 0
        return self.state, reward, done, {}

    def reset(self):
        observations = np.array(self.jd.reset())
        self.state = observations[0:-1]
        self.steps_beyond_done = 0
        return self.state

    def render(self, mode='human'):

        self.jd.render()
        return None

    def close(self):
        shutdownJVM()
        if self.viewer:
            self.viewer.close()
            self.viewer = None
