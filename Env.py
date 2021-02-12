import os
import numpy as np
import numpy.random as rd


def decorate_env(env):
    if not all([hasattr(env, attr) for attr in (
            'env_name', 'state_dim', 'action_dim', 'target_reward', 'if_discrete')]):
        (env_name, state_dim, action_dim, action_max, if_discrete, target_reward) = get_gym_env_information(env)
        setattr(env, 'env_name', env_name)
        setattr(env, 'state_dim', state_dim)
        setattr(env, 'action_dim', action_dim)
        setattr(env, 'if_discrete', if_discrete)
        setattr(env, 'target_reward', target_reward)
    return env


def get_gym_env_information(env) -> (str, int, int, float, bool, float):
    import gym  # gym of OpenAI is not necessary for ElegantRL (even RL)
    gym.logger.set_level(40)  # Block warning: 'WARN: Box bound precision lowered by casting to float32'
    assert isinstance(env, gym.Env)

    env_name = env.unwrapped.spec.id

    state_shape = env.observation_space.shape
    state_dim = state_shape[0] if len(state_shape) == 1 else state_shape  # sometimes state_dim is a list

    if_discrete = isinstance(env.action_space, gym.spaces.Discrete)
    if env.spec.reward_threshold is None: 
        target_reward = 2 ** 16
        print(f"| env.spec.reward_threshold is None, so I set target_reward={target_reward}")
    else:
        target_reward = env.spec.reward_threshold

    if if_discrete:  # make sure it is discrete action space
        action_dim = env.action_space.n
        action_max = int(1)
    elif isinstance(env.action_space, gym.spaces.Box):  # make sure it is continuous action space
        action_dim = env.action_space.shape[0]
        action_max = float(env.action_space.high[0])
    else:
        raise RuntimeError('| Please set these value manually: if_discrete=bool, action_dim=int, action_max=1.0')
    return env_name, state_dim, action_dim, action_max, if_discrete, target_reward


class FinanceMultiStockEnv:  # 2021-02-02
    """FinRL
    Paper: A Deep Reinforcement Learning Library for Automated Stock Trading in Quantitative Finance
           https://arxiv.org/abs/2011.09607 NeurIPS 2020: Deep RL Workshop.
    Source: Github https://github.com/AI4Finance-LLC/FinRL-Library
    Modify: Github Yonv1943 ElegantRL
    """

    def __init__(self, initial_account=1e6, transaction_fee_percent=1e-3, max_stock=100):
        self.stock_dim = 30
        self.initial_account = initial_account
        self.transaction_fee_percent = transaction_fee_percent
        self.max_stock = max_stock

        self.ary = self.load_training_data_for_multi_stock()
        assert self.ary.shape == (1699, 5 * 30)  # ary: (date, item*stock_dim), item: (adjcp, macd, rsi, cci, adx)

        # reset
        self.day = 0
        self.account = self.initial_account
        self.day_npy = self.ary[self.day]
        self.stocks = np.zeros(self.stock_dim, dtype=np.float32)  # multi-stack
        self.total_asset = self.account + (self.day_npy[:self.stock_dim] * self.stocks).sum()
        self.episode_return = 0.0  # Compatibility for ElegantRL 2020-12-21

        '''env information'''
        self.env_name = 'FinanceStock-v1'
        self.state_dim = 1 + (5 + 1) * self.stock_dim
        self.action_dim = self.stock_dim
        self.if_discrete = False
        self.target_reward = 15
        self.max_step = self.ary.shape[0]

        self.gamma_r = 0.0

    def reset(self):
        self.account = self.initial_account * rd.uniform(0.9, 1.0)  # notice reset()
        self.stocks = np.zeros(self.stock_dim, dtype=np.float32)
        self.total_asset = self.account + (self.day_npy[:self.stock_dim] * self.stocks).sum()
        # total_asset = account + (adjcp * stocks).sum()

        self.day = 0
        self.day_npy = self.ary[self.day]
        self.day += 1

        state = np.hstack((self.account * 2 ** -16,
                           self.day_npy * 2 ** -8,
                           self.stocks * 2 ** -12,), ).astype(np.float32)

        return state

    def step(self, actions):
        actions = actions * self.max_stock

        """bug or sell stock"""
        for index in range(self.stock_dim):
            action = actions[index]
            adj = self.day_npy[index]
            if action > 0:  # buy_stock
                available_amount = self.account // adj
                delta_stock = min(available_amount, action)
                self.account -= adj * delta_stock * (1 + self.transaction_fee_percent)
                self.stocks[index] += delta_stock
            elif self.stocks[index] > 0:  # sell_stock
                delta_stock = min(-action, self.stocks[index])
                self.account += adj * delta_stock * (1 - self.transaction_fee_percent)
                self.stocks[index] -= delta_stock

        """update day"""
        self.day_npy = self.ary[self.day]
        self.day += 1
        done = self.day == self.max_step  # 2020-12-21

        state = np.hstack((
            self.account * 2 ** -16,
            self.day_npy * 2 ** -8,
            self.stocks * 2 ** -12,
        ), ).astype(np.float32)

        next_total_asset = self.account + (self.day_npy[:self.stock_dim] * self.stocks).sum()
        reward = (next_total_asset - self.total_asset) * 2 ** -16  # notice scaling!
        self.total_asset = next_total_asset

        self.gamma_r = self.gamma_r * 0.99 + reward  # notice: gamma_r seems good? Yes
        if done:
            reward += self.gamma_r
            self.gamma_r = 0.0  # env.reset()

            # cumulative_return_rate
            self.episode_return = next_total_asset / self.initial_account

        return state, reward, done, None

    @staticmethod
    def load_training_data_for_multi_stock(if_load=True):  # need more independent
        npy_path = './FinanceMultiStock.npy'
        if if_load and os.path.exists(npy_path):
            data_ary = np.load(npy_path).astype(np.float32)
            assert data_ary.shape[1] == 5 * 30
            return data_ary
        else:
            raise RuntimeError(
                f'| FinanceMultiStockEnv(): Can you download and put it into: {npy_path}\n'
                f'| https://github.com/Yonv1943/ElegantRL/blob/master/FinanceMultiStock.npy'
                f'| Or you can use the following code to generate it from a csv file.'
            )

        # from preprocessing.preprocessors import pd, data_split, preprocess_data, add_turbulence
        #
        # # the following is same as part of run_model()
        # preprocessed_path = "done_data.csv"
        # if if_load and os.path.exists(preprocessed_path):
        #     data = pd.read_csv(preprocessed_path, index_col=0)
        # else:
        #     data = preprocess_data()
        #     data = add_turbulence(data)
        #     data.to_csv(preprocessed_path)
        #
        # df = data
        # rebalance_window = 63
        # validation_window = 63
        # i = rebalance_window + validation_window
        #
        # unique_trade_date = data[(data.datadate > 20151001) & (data.datadate <= 20200707)].datadate.unique()
        # train__df = data_split(df, start=20090000, end=unique_trade_date[i - rebalance_window - validation_window])
        # # print(train__df) # df: DataFrame of Pandas
        #
        # train_ary = train__df.to_numpy().reshape((-1, 30, 12))
        # '''state_dim = 1 + 6 * stock_dim, stock_dim=30
        # n   item    index
        # 1   ACCOUNT -
        # 30  adjcp   2
        # 30  stock   -
        # 30  macd    7
        # 30  rsi     8
        # 30  cci     9
        # 30  adx     10
        # '''
        # data_ary = np.empty((train_ary.shape[0], 5, 30), dtype=np.float32)
        # data_ary[:, 0] = train_ary[:, :, 2]  # adjcp
        # data_ary[:, 1] = train_ary[:, :, 7]  # macd
        # data_ary[:, 2] = train_ary[:, :, 8]  # rsi
        # data_ary[:, 3] = train_ary[:, :, 9]  # cci
        # data_ary[:, 4] = train_ary[:, :, 10]  # adx
        #
        # data_ary = data_ary.reshape((-1, 5 * 30))
        #
        # os.makedirs(npy_path[:npy_path.rfind('/')])
        # np.save(npy_path, data_ary.astype(np.float16))  # save as float16 (0.5 MB), float32 (1.0 MB)
        # print('| FinanceMultiStockEnv(): save in:', npy_path)
        # return data_ary
