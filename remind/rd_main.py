from tkinter import messagebox
from binance.websocket.websocket_client import BinanceWebsocketClient
import time, json
from sqlalchemy import Column, String, Integer, create_engine, ForeignKey, and_
from sqlalchemy.orm import sessionmaker, relationship, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from binance.um_futures import UMFutures

import numpy as np
import pandas as pd
import requests
import threading

Base = declarative_base()
class Plans(Base):
    __tablename__ = 'plans'

    idp = Column(String(20), primary_key=True) # ID
    symbol = Column(String(20), nullable=False) # 交易对
    price = Column(String(10)) # 价格
    remark = Column(String(200)) # 备注
    side = Column(String(10)) # 方向 多空？
    status = Column(Integer, nullable=False, default=0) # 0未提醒，1已提醒

symbols = {
    # 'BTC': {
    #     'binance': 'BTCUSDT',
    #     'priceDecimal': 1, # 价格小数
    #     'buyQuantityDecimal': 3, # 买入小数
    # },
    'ETH': {
        'binance': 'ETHUSDT',
        'priceDecimal': 2, # 金额小数
        'buyQuantityDecimal': 3, # 买入小数
    },
}
plans = {
    '2000-2005': {
        'idp': 'sfsdf333'
    },
    '1990-1992': {
        'idp': 'sfsdf333'
    }
}

class KdataTips:

    def __init__(self, db):
        wss_url = "wss://fstream.binance.com/ws"
        self.volCcyQuotes = {}
        self.binance = UMFutures(key='c3k2NQMHnq8gI4SMPVmhZ06dhZ5VMYqr3TlWokvzKbuNbl74gnmGDbmmfxHx0yFX',
                                 secret='c5UJ5JPUJchqQSvPmFWgW1hTVvkteoTBfP5hsVaiBkoeWg0VINAF7nc62ELWjFsE')

        self.db = db

        for symbol in symbols.keys():
            symbol = symbol + "USDT"
            wss_url += "/" + str(symbol).lower() + '@kline_5m'
            if symbol not in self.volCcyQuotes:
                line5m = self.binance.klines(symbol, interval='5m', limit=1000)
                line5m = pd.DataFrame(np.array(line5m), columns=["timestamp", "open", "high", "low", "close", "volume", "entimestamp", "volCcyQuote", "clinchNum", "buyVolume", "buyVolCcyQuote", "hulue"])

                line5m = line5m.drop('entimestamp', axis='columns')
                line5m = line5m.drop('hulue', axis='columns')

                line5m["volume"] = line5m["volume"].astype(float)  # 成交额
                self.volCcyQuotes[symbol] = line5m["volume"].to_list()

        print(wss_url)
        self.binance_k_ws = BinanceWebsocketClient(stream_url=wss_url, on_message=self.__ws_message_handler)

    # def call_api(self, symbol, nprice, remark=None):

    def remind_wx(self,_type, params):
        # 发送微信提示 2秒发送一次， 发送5次
        symbol = params['symbol']
        nprice = params['nprice']

        for i in range(2):
            if _type == 'heat':
                requests.post('http://152.32.243.56/addRemind', json={
                    "instId": symbol,
                    "style": _type,
                    "price": nprice
                })
            if _type == 'plan':
                requests.post('http://152.32.243.56/addRemind', json={
                    "instId": symbol,
                    "style": 'plan',
                    "price": nprice,
                    "remark": params['remark']
                })
            time.sleep(3)
    def __ws_message_handler(self, _, message):
        message = json.loads(message)
        k = message['k']
        # print("k", k)
        symbol = message['s']
        if k['x']:
            new_price = float(k['c'])
            print("new_price", new_price)

            isheat = self.get_heat_coin(self.volCcyQuotes[symbol] + [float(k['v'])])
            if isheat:
                api_thread = threading.Thread(target=self.remind_wx, args=('heat', {
                    "symbol": symbol,
                    "nprice": new_price
                }))
                api_thread.start()

            self.volCcyQuotes[symbol].append(float(k['v']))

            plans = self.db.query(Plans).filter(and_(Plans.symbol == symbol, Plans.status == 0)).all()  # 查询未提醒的计划
            remind_plans = None
            for plan in plans:
                print(plan.price, plan.side)
                plan_price = float(plan.price)

                if plan.side == 'short':
                    l_price = float(k['l'])
                    if l_price <= plan_price: # 说明价格跌倒我的计划之下， 我的计划是价格跌倒这里
                        remind_plans = {
                            "nprice": new_price,
                            "side": "short",
                            "remark": plan.remark
                        }
                        plan.status = 1

                if plan.side == 'long':
                    h_price = float(k['h'])
                    if h_price >= plan_price: # 说明价格涨到我的计划之上
                        remind_plans = {
                            "nprice": new_price,
                            "side": "long",
                            "remark": plan.remark
                        }
                        plan.status = 1

            if remind_plans is not None:
                print("remind_plans", remind_plans)
                remind_plans['symbol'] = symbol
                self.db.commit()

                api_thread = threading.Thread(target=self.remind_wx, args=('plan', remind_plans))
                api_thread.start()


    def get_heat_coin(self, volumes):
        length = 610
        slength = 610

        # print("volumes =》", volumes)
        length = min(length, len(volumes))
        slength = min(slength, len(volumes))

        # ma = calculate_ma(volumes, length)

        mean = np.mean(volumes[-length:])
        std = self.pstdev(volumes, slength)
        stdbar = (np.array(volumes) - mean) / std

        # print(inst_name, ": mean", mean, "std", std, "stdbar", stdbar[-1])
        # print(new_volume, ma[-1])
        if stdbar[-1] > 4:
            return True

        return False

    def pstdev(self, series, period):
        mean = np.mean(series[-period:])
        summation = 0.0
        for sample in series[-period:]:
            sample_minus_mean = sample - mean
            summation += sample_minus_mean * sample_minus_mean
        return np.sqrt(summation / period)

if __name__ == '__main__':
    engine = create_engine('mysql+pymysql://xuhappy:Xu015106@rm-bp1e8nn46n6ce698tro.mysql.rds.aliyuncs.com:3306/trade?charset=utf8mb4&autocommit=true', pool_recycle=60 * 5, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine)
    db = scoped_session(session_factory)
    KdataTips(db)

    # 启动个定时器， 2分钟获取一下 计划