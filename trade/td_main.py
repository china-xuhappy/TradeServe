# 主要用于 连接币安websocket的 一些处理， 运行在树莓派上
# 运行在window上 可能会出现关闭 等行为

# 在服务器上 使用shell语句 半小时重启一下
import random
from binance.um_futures import UMFutures
from binance.websocket.websocket_client import BinanceWebsocketClient
from binance.error import ClientError
import time, json
from sqlalchemy import create_engine, and_
from module import Order, SubOrder
from config import symbolsDecimal
from sqlalchemy.orm import sessionmaker, scoped_session
import requests

class Binance:
    def __init__(self):
        engine = create_engine(
            'mysql+pymysql://xuhappy:Xu015106@rm-bp1e8nn46n6ce698tro.mysql.rds.aliyuncs.com:3306/trade?charset=utf8mb4&autocommit=true',
            pool_recycle=60 * 5, pool_pre_ping=True)
        session_factory = sessionmaker(bind=engine)
        self.db = scoped_session(session_factory)

    def connect(self):
        self.binance = UMFutures(key='c3k2NQMHnq8gI4SMPVmhZ06dhZ5VMYqr3TlWokvzKbuNbl74gnmGDbmmfxHx0yFX', secret='c5UJ5JPUJchqQSvPmFWgW1hTVvkteoTBfP5hsVaiBkoeWg0VINAF7nc62ELWjFsE')
        self.listenKey = self.binance.new_listen_key()['listenKey']
        self.binance_ws = BinanceWebsocketClient(stream_url="wss://fstream.binance.com/ws/" + self.listenKey, on_message=self.ws_message_handler, on_error=self.__ws_error_handler)
        self.send_ws_order_trade()

    def send_ws_order_trade(self):
        # 发送 币安websocket 订单变化事件
        json_msg = {"method": "REQUEST", "params": [
            self.listenKey + "@ORDER_TRADE_UPDATE"
        ], "id": 200115}

        self.binance_ws.send(json_msg)

    def __ws_error_handler(self, _, message):
        print('__ws_error_handler: ', message)
        if type(message) == ClientError:
            if message.error_code == -1125: # 不存在
                self.listenKey = self.binance.new_listen_key()['listenKey']
                print("__ws_error_handler 不存在了 self.listenKey", self.listenKey)
                self.send_ws_order_trade()
        else:
            print(type(message), message)
        #     如收到-1125报错提示此listenKey不存在，建议重新使用POST /fapi/v1/listenKey生成listenKey并用新listenKey建立连接

    def ws_message_handler(self, _, message):
        print('__ws_message_handler: ', _, message)
        message = json.loads(message)
        if 'e' in message:
            e = message['e']  # 事件

            if e == 'listenKeyExpired':
                print('过期啦 更新 延长时间', e)
                try:
                    self.binance.renew_listen_key(message['listenKey'])
                except ClientError as ee:
                    if ee.status_code == -1125:
                        print("__ws_message_handler This listenKey does not exist.")

                        self.listenKey = self.binance.new_listen_key()['listenKey']
                        print("__ws_message_handler 不存在了 self.listenKey", self.listenKey)
                        self.send_ws_order_trade()

            if e == 'ORDER_TRADE_UPDATE':
                obj = message['o']  # 对象
                WsProcess(obj, self.binance, self.db)
                self.heal_status = True # 表示收到websocket

            if e == 'ACCOUNT_UPDATE':
                a = message['a']  # 对象
                usdt = a['B'][0]
                if usdt['a'] == 'USDT':
                    print('account', usdt['wb'])

    def commit_order(self, params, isbinance = True ,issub = False):
        # 提交订单 倒币安
        # issub True 子订单， False 主订单
        # isbinance 是否上币安？ False不上，True 提交
        other_params = params['other']
        commit_params = params['commit']

        symbol = params['symbol']
        side = params['side']
        type = params['type']

        positionSide = commit_params['positionSide']
        price = '0.0'
        if type == 'STOP_MARKET' or type == 'TAKE_PROFIT_MARKET': # 市价止盈止损 用stopPrice
            price = commit_params['stopPrice']
        else:
            if type != 'MARKET':
                price = commit_params['price']

        if 'closePosition' in commit_params and commit_params['closePosition'] == True:
            order_quantity = other_params['quantity']
        else:
            order_quantity = commit_params['quantity']

        order = None
        suborder_info = None
        newClientOrderId = "SYSTEM_ERROR"

        priceDecimal = symbolsDecimal[symbol]['priceDecimal']
        price =  round(float(price), priceDecimal) if priceDecimal > 0 else int(price)

        buyQuantityDecimal = symbolsDecimal[symbol]['buyQuantityDecimal']
        order_quantity = round(float(order_quantity), buyQuantityDecimal) if buyQuantityDecimal > 0 else int(order_quantity)

        if issub == False: # 主订单
            principal = other_params['margin']
            porderid = str(int(time.time())) + str(random.randint(20000, 99099)) # 新订单 随机生成
            cust_orderid = other_params['cust_orderid'] # 新订单用自定义ID 来做关联

            order = Order(orderid=porderid, symbol=symbol, side=positionSide, price=price,
                          tqty=str(order_quantity),
                          aqty=str(order_quantity), margin=principal,
                          way=type, isend=4, plstatus='自己系统挂单', placcount='0.0', cust_orderid=cust_orderid)
            self.db.add(order)
        else:
            porderid = other_params['porderid']
            status = other_params['status']
            newClientOrderId = status + ":" + str(porderid)

            # porderid 这里还没提交到交易所 要先生成一个临时ID， 关联上，真正生成订单，再把父ID更换

            suborder_info = SubOrder(orderid=str(int(time.time())) + str(random.randint(10000, 99099)), porderid=porderid, way=type,
                                     status=status, qty=str(order_quantity), price=str(price),
                                     rp='0.0', side=positionSide, bs=side, tstatus='自己系统挂单', isend=3)  # 子订单
            self.db.add(suborder_info)

        self.db.commit()
        order_info = {
            'orderId': porderid
        }
        if isbinance:
            try:
                if issub:
                    commit_params['newClientOrderId'] = newClientOrderId

                if type == 'STOP_MARKET' or type == 'TAKE_PROFIT_MARKET':  # 市价止盈止损 用stopPrice
                    price = commit_params['stopPrice']
                    commit_params['stopPrice'] = price
                else:
                    if type != 'MARKET':
                        commit_params['price'] = price

                if 'closePosition' not in commit_params:
                    commit_params['quantity'] = order_quantity

                order_info = self.binance.new_order(symbol=symbol, side=side, type=type, **commit_params)
            except Exception as e:
                # 下单失败
                print(e)

            orderid = order_info['orderId']
            if order is not None:
                order.orderid = orderid
                order.plstatus = '交易所挂单'
                order.isend = 2

            if suborder_info is not None:
                suborder_info.orderid = orderid
                suborder_info.isend = 0
                suborder_info.tstatus = '交易所挂单'

        self.db.commit()
        if order is not None:
            self.db.refresh(order)

        if suborder_info is not None:
            self.db.refresh(suborder_info)
        return order_info

class WsProcess(Binance):
    """ws socket 的订单处理"""
    # 交易这一块有几步
    # 第一 刚开始提交订单 成交 START，需要修改订单状态为进行中
    # 第二 被止损 STOP_MARKET，需要修改订单状态 和 把之前挂单全部撤销
    # 第三 止盈 需要修改子订单状态
    # 第四 止盈第二步，需要修改主订单 20%的状态

    # 还有一个终结止盈，就是那20%的止盈，也要改变主状态

    # 第五 开对手盘的东西 等下再思考（可能是 终结订单 帮忙自动开单 修改订单等等），
    def __init__(self, obj, binance, db):
        self.db = db
        super().__init__()
        self.binance = binance

        self.s = obj['s']  # 交易对
        c = obj['c']  # 自定义ID START开始，END_STOP最终止损， END_PROFIT最终止盈，PROFIT_STEP1(第一步止盈) PROFIT_STEP2(第二步止止盈)
        self.S = obj['S']  # 订单方向 BUY SELL
        self.order_type = obj['o']  # 订单类型 LIMIT 限价单  MARKET 市价单  STOP 止损限价单# STOP_MARKET 止损市价单# TAKE_PROFIT 止盈限价单# TAKE_PROFIT_MARKET 止盈市价单# TRAILING_STOP_MARKET 跟踪止损单
        self.now_run_type = obj['x']  # 本次事件具体执行类型 NEW CANCELED 已撤   CALCULATED 订单ADL或爆仓   EXPIRED 订单失效   TRADE 交易   AMENDMENT 订单修改
        self.now_order_type = obj['X']  # 当前订单状态 NEW PARTIALLY_FILLED(部分成交)  FILLED（全部成交） CANCELED（取消） EXPIRED EXPIRED_IN_MATCH

        T = obj['T']  # 成交时间
        self.pside = obj['ps']  # 持仓方向 LONG SHORT
        self.rp = obj['rp']  # 本次交易实现盈利
        self.order_last_price = obj['L'] # 订单末次成交价格

        self.origin_order_type = obj['ot'] # 原始订单类型

        p = obj['p']  # 价格
        if ":" in c:
            self.status = c[: c.index(':')]  # 切割一下自定义订单类型
            self.porderid = c[c.index(":") + 1:]
        else:
            self.status = 'BINANCE'

        print("obj", obj)
        self.binance_orderid = obj['i']  # ID
        self.order_last_qty = obj['l']  # 订单末次成交量， 可能部分成交

        self.db.commit() # 先刷新一下数据库 预防缓存
        self.suborder_info = self.db.query(SubOrder).filter_by(orderid=self.binance_orderid).first()  # 子订单

        if self.now_run_type == 'TRADE':
            if self.status == 'START':  # 主订单
                self.db.commit()
                self.order_info = self.db.query(Order).filter_by(orderid=self.binance_orderid).first()  # 主订单
                # 等对手盘开单成功，要把当前方向的止损给取消了，形成对冲
                self.start_order()
            else:
                # 子订单
                self.order_info = self.db.query(Order).filter_by(orderid=self.porderid).first()  # 主订单
                if self.status == 'END_STOP':
                    self.stop_order()

                # PROTECT 保本平仓
                # PROFIT_1 PROFIT_2 止盈一 和 止盈二 平仓
                # PROFIT_20 止盈20%，被动止盈
                # 应该还有一个 当对手盘新出来一个20%时，要把之前的20%平仓， 市场上一直只有一个20%

                # END_PROFIT_20 继续开当前方向的，帮忙把20%平仓（是主动的）
                # HELP_PROFIT_2 开对手盘 发现还未到达20%，帮忙把仓位平掉，剩20% （主动的）
                if self.status in ['PROTECT', 'PROFIT_1', 'PROFIT_2', 'PROFIT_20', 'DRIVING_PROFIT_2']: # 止盈的 # 20 生成止盈时 也要加上这个类型可以作为 PROFIT_20
                    self.profit_order()

        self.message_tips()

    def start_order(self):
        # 订单开始， 可能存在对手订单 等等处理
        if self.order_info is not None: # 必须是交易所挂单 然后成交的
            if self.order_type == 'MARKET':  # 市价单价格不确认（再次更新），限价单在下单时已确认
                self.order_info.price = self.order_last_price

            self.order_info.isend = 0
            self.order_info.plstatus = '进行中'
            self.order_info.placcount = '0.0'
            self.db.commit()

            me_sub_orders = self.db.query(SubOrder).filter(and_(SubOrder.porderid == self.order_info.cust_orderid, SubOrder.isend == 3)).all()
            if me_sub_orders is not None:
                for me_sub_order in me_sub_orders:
                    price = round(float(me_sub_order.price), symbolsDecimal[self.order_info.symbol]['priceDecimal'])
                    qty = round(float(me_sub_order.qty), symbolsDecimal[self.order_info.symbol]['buyQuantityDecimal'])

                    order_info = self.binance.new_order(symbol=self.order_info.symbol, side=me_sub_order.bs, type=me_sub_order.way, **{
                        "quantity": qty,
                        "stopPrice": price,
                        "positionSide": me_sub_order.side,
                        "timeInForce": "GTC",
                        "priceProtect": True,
                        "newClientOrderId": me_sub_order.status + self.order_info.orderid
                    })

                    me_sub_order.isend = 0  # 已经被挂单
                    me_sub_order.orderid = order_info['orderId']
                    me_sub_order.tstatus = '交易所挂单'
                    me_sub_order.porderid = self.order_info.orderid

                self.db.commit()
            else:
                pass #TODO 发出通知： 交易所成交时，未查到子订单的系统挂单，无法为子订单提交交易所

            # --------------------------------处理对手盘 1.帮对手盘把止盈放在当前方向止损的前面, 2. 帮对手盘取消止损的挂单 ----------------------------------------------
            # 例如现在多方向 已经达到20%， 我现在开空， 我是帮多 设置止盈 把止损撤销
            # reverse_side = 'SHORT' if self.order_info.side == 'LONG' else 'LONG'
            # reverse_order = self.db.query(Order).filter(
            #     and_(Order.symbol == self.order_info.symbol, Order.side == reverse_side, Order.isend == 0)).first()  # 查询当前方向 进行中 和 挂单
            #
            # if reverse_order is not None: # 查看是否有对手盘
            #     if reverse_order.twenty == 1: # 对手盘 已经到达第二步
            #
            #         # 先获取当前方向的止损价， 然后再创建对手盘的止盈， 然后再撤销对手盘的止损
            #         current_stop_order = self.db.query(SubOrder).filter(
            #             and_(SubOrder.porderid == self.order_info.orderid, SubOrder.isend == 0, SubOrder.status == 'END_STOP')).first()  #
            #
            #         stop_loss_price = float(current_stop_order.price)
            #         if reverse_order.side == 'LONG':
            #             stop_loss_price -= 1
            #             side = 'SELL'
            #         else:
            #             stop_loss_price += 1
            #             side = 'BUY'
            #
            #         # 其实最后止盈 我并不关心是多少量， 直接到达价格止盈就可以，如果关心量 可能会止盈失败 等等
            #
            #         self.commit_order({"symbol": reverse_order.symbol, "side": side, "type": "TAKE_PROFIT_MARKET",
            #                "commit": {
            #                    "stopPrice": str(stop_loss_price),
            #                    "positionSide": reverse_order.side,
            #                    "closePosition": True,
            #                    "priceProtect": True
            #                },
            #                "other": {"porderid": reverse_order.orderid, "status": "PROFIT_20", "quantity": str(reverse_order.aqty)}
            #         }, issub=True)
            #
            #         reverse_stop_order = self.db.query(SubOrder).filter(
            #             and_(SubOrder.porderid == reverse_order.orderid, SubOrder.isend == 0, SubOrder.status == 'END_STOP')).first()  #
            #
            #         if reverse_stop_order is not None:
            #             self.binance.cancel_order(symbol=reverse_order.symbol, orderId=reverse_stop_order.orderid)
            #     else:
            #         if reverse_order.twenty == 0:
            #             reverse_profits = self.db.query(SubOrder).filter(
            #                 and_(SubOrder.porderid == reverse_order.orderid, SubOrder.isend == 0,
            #                      SubOrder.status != 'END_STOP')).all()  #撤销所有非止损的订单
            #
            #             if reverse_profits is not None:
            #                 orderIdList = []
            #                 for reverse_profit in reverse_profits:
            #                     orderIdList.append(int(reverse_profit.orderid))
            #
            #                 if len(orderIdList) > 0:  # 撤销所有当前方向子订单
            #                     self.binance.cancel_batch_order(symbol=self.order_info.symbol, orderIdList=orderIdList, origClientOrderIdList=[])
            #
            #             aqty = float(reverse_order.aqty)
            #             side = 'SELL' if reverse_order.side == 'LONG' else 'BUY'
            #             # 帮忙平仓 - 留20%的仓 来作为反方向止盈,   # 留20%左右仓位 给到最后， 可以对冲做单
            #             take_profit2_quantity = aqty - (0.2 * aqty)  # 最后留的
            #             # TODO 这里不能直接平仓，我挂单很低 你现在市价成交 不是很有问题， 只能说在成交时 看对手盘，然后帮忙成交
            #             # 帮忙平仓 然后留20%，需要把20%的止盈位置 设置在止损。 那就是先平仓，再次下单 再设置。
            #             self.commit_order({"symbol": reverse_order.symbol, "side": side, "type": "MARKET",
            #                    "commit": {
            #                        "quantity": str(take_profit2_quantity),
            #                        "positionSide": reverse_order.side
            #                    },
            #                    "other": {
            #                        "porderid": reverse_order.orderid,
            #                        "status": "DRIVING_PROFIT_2"
            #                    }
            #            }, issub=True)
            #
            #             reverse_order.aqty = str(0.2 * aqty)
            #             self.db.commit()
            #             # TODO DRIVING_PROFIT_2内 还有20% 需要设置为止盈，把止损都撤销
    def stop_order(self):
        # 被止损时 - 获取所有挂单的子订单， 包括止损订单。 都要改为撤销
        if self.now_order_type == 'PARTIALLY_FILLED':
            suborder_info = self.db.query(SubOrder).filter(
                and_(SubOrder.porderid == self.porderid, SubOrder.isend == 0, SubOrder.way == 'STOP_MARKET',
                     SubOrder.status == 'END_STOP')).first()  # 查一下是否有部分成交的
            suborder_info.rp = float(suborder_info.rp) + float(self.order_last_qty)
            suborder_info.qty = float(suborder_info.qty) + float(self.order_last_qty)  # 应该不需要小数位
            suborder_info.tstatus = self.now_order_type
            self.db.commit()

        if self.now_order_type == 'FILLED':
            suborder_infos = self.db.query(SubOrder).filter(
                and_(SubOrder.porderid == self.porderid, SubOrder.isend == 0)).all()  # 查一下是否有部分成交的
            orderIdList = []
            nowrp = 0
            for suborder_info in suborder_infos:
                # suborder_info.isend = 1 # 这个地方不需要 赋值，撤回订单的时候，在取消事件会对订单做状态修改
                if suborder_info.way == 'STOP_MARKET' and suborder_info.status == 'END_STOP':
                    if suborder_info.tstatus == 'PARTIALLY_FILLED':  # 把之前部分成交的 再加一下
                        suborder_info.rp = float(suborder_info.rp) + float(self.rp)
                        suborder_info.qty = float(suborder_info.qty) + float(self.order_last_qty)
                    else:
                        suborder_info.rp = float(self.rp)
                        suborder_info.qty = float(self.order_last_qty)
                    suborder_info.tstatus = self.now_order_type
                    suborder_info.isend = 1
                    nowrp = suborder_info.rp
                else:
                    # 除了止损以往的订单 都要撤回， 因为订单都没了。
                    orderIdList.append(int(suborder_info.orderid))

            nowrp = float(nowrp)
            if self.order_info is not None:
                if nowrp > 0:
                    self.order_info.plstatus = '盈利'
                elif nowrp < 0:
                    self.order_info.plstatus = '亏损'

                self.order_info.isend = 1
                self.order_info.placcount = str(nowrp)
                self.order_info.aqty = '0'
                self.order_info.way = self.origin_order_type

                if len(orderIdList) > 0:  # 撤销所有当前方向子订单
                    self.binance.cancel_batch_order(symbol=self.order_info.symbol, orderIdList=orderIdList, origClientOrderIdList=[])

            self.db.commit()

    def profit_order(self):
        """
        止盈 的订单，这个地方 非常重要
        :return:
        """
        if self.order_info is not None:
            buyQuantityDecimal = symbolsDecimal[self.order_info.symbol]['buyQuantityDecimal']

            if self.suborder_info.tstatus == 'PARTIALLY_FILLED' and self.now_order_type == 'FILLED': # 如果之前是部分成交，现在是全部成交 需要重新修改数据
                quantity = float(self.suborder_info.rp) + float(self.rp)
                if buyQuantityDecimal > 0:
                    quantity = round(quantity, buyQuantityDecimal)
                else:
                    quantity = int(quantity)

                self.suborder_info.rp = quantity
            else:
                self.suborder_info.rp = float(self.rp)

            if self.now_order_type == 'FILLED':
                self.suborder_info.isend = 1
                self.suborder_info.tstatus = self.now_order_type
                self.suborder_info.price = str(self.order_last_price)

                nowrp = float(self.suborder_info.rp) + float(self.order_info.placcount)
                if nowrp > 0:
                    self.order_info.plstatus = '盈利'
                elif nowrp < 0:
                    self.order_info.plstatus = '亏损'
                self.order_info.placcount = str(nowrp)

                quantity = float(self.order_info.aqty) - float(self.suborder_info.qty)
                if buyQuantityDecimal > 0:
                    quantity = round(quantity, buyQuantityDecimal)
                else:
                    quantity = int(quantity)

                self.order_info.aqty = str(quantity)
                self.order_info.status = self.suborder_info.status # 主订单的状态

            self.db.commit()

        if self.suborder_info.status == 'PROTECT':
            #保本后，把止损价移动到开仓价，
            sub_order = self.db.query(SubOrder).filter(and_(SubOrder.porderid == self.order_info.orderid, SubOrder.way == 'STOP_MARKET', SubOrder.status == 'END_STOP', SubOrder.isend == 0)).first()
            if sub_order.isend == 0:
                open_price = float(self.order_info.price)
                self.binance.cancel_order(symbol=self.order_info.symbol, orderId=sub_order.orderid)

                self.commit_order({"symbol": self.order_info.symbol, "side": sub_order.bs, "type": "STOP_MARKET",
                           "commit": {
                               "closePosition": True,
                               "stopPrice": str(open_price),
                               "positionSide": sub_order.side,
                               "priceProtect": True
                           },
                           "other": { "porderid": self.order_info.orderid, "status": "END_STOP", "quantity": str(sub_order.qty) }
               }, issub=True)

                # TODO 还要把对手盘的20% 的止盈 也设置在止损上面（或者止损）
                reverse_side = 'SHORT' if self.order_info.side == 'LONG' else 'LONG'
                opposite_side_progress = self.db.query(Order).filter(
                    and_(Order.symbol == self.order_info.symbol, Order.side == reverse_side, Order.isend == 0)).first()  # 查询当前方向 进行中 和 挂单

                if opposite_side_progress is not None and opposite_side_progress.twenty == 1:
                    opposite_sub_orders = self.db.query(SubOrder).filter(
                        and_(SubOrder.porderid == opposite_side_progress.orderid, SubOrder.status == 'PROFIT_20',
                             SubOrder.isend == 0)).first()
                    if opposite_sub_orders is not None:
                        self.binance.cancel_order(symbol=self.order_info.symbol, orderId=opposite_sub_orders.orderid)

                        if opposite_side_progress.side == 'LONG':
                            open_price -= 1
                        else:
                            open_price += 1

                        self.commit_order(
                            {"symbol": self.order_info.symbol, "side": opposite_sub_orders.bs, "type": "TAKE_PROFIT_MARKET",
                             "commit": {
                                 "quantity": opposite_sub_orders.aqty,
                                 "stopPrice": str(open_price),
                                 "positionSide": opposite_sub_orders.side,
                                 "timeInForce": "GTC",
                                 "priceProtect": True,
                             },
                             "other": {"porderid": opposite_sub_orders.porderid, "status": "PROFIT_20"}
                         }, issub=True)


        if self.suborder_info.status == 'PROFIT_1':
            pass # 保本1

        # if self.suborder_info.status == 'DRIVING_PROFIT_2': # 主动发起平仓 倒20%， 主动的这个订单是要设置止盈的，然后把止损撤销
        #     if self.order_info is not None:
        #
        #         reverse_side = 'SHORT' if self.order_info.side == 'LONG' else 'LONG'
        #         reverse_order = self.db.query(Order).filter(
        #             and_(Order.symbol == self.order_info.symbol, Order.side == reverse_side, Order.isend == 0)).first()  # 查询当前方向 进行中 和 挂单
        #
        #         reverse_stop_order = self.db.query(SubOrder).filter(
        #             and_(SubOrder.porderid == reverse_order.orderid, SubOrder.isend == 0, SubOrder.status == 'END_STOP')).first()  #
        #
        #         stop_loss_price = float(reverse_stop_order.price)
        #         now_stop_order = self.db.query(SubOrder).filter(and_(SubOrder.porderid == self.order_info.orderid, SubOrder.isend == 0, SubOrder.status == 'END_STOP')).first()  #
        #
        #         if now_stop_order.side == 'LONG':
        #             stop_loss_price -= 1
        #         else:
        #             stop_loss_price += 1
        #
        #         self.commit_order({"symbol": self.order_info.symbol, "side": now_stop_order.bs, "type": "TAKE_PROFIT_MARKET",
        #                "commit": {
        #                    "stopPrice": str(stop_loss_price),
        #                    "positionSide": now_stop_order.side,
        #                    "closePosition": True,
        #                    "priceProtect": True,
        #                },
        #                "other": {"porderid": self.order_info.orderid, "status": "PROFIT_20", "quantity": str(self.order_info.aqty)}
        #            }, issub=True)
        #
        #         if now_stop_order is not None: # 把当前方向 止损取消了
        #             self.binance.cancel_order(symbol=self.order_info.symbol, orderId=now_stop_order.orderid)
        #
            # self.db.commit()

        if self.suborder_info.status == 'PROFIT_2':
            #TODO 这里属于当前方向新出来20%， 要不要把对手20%平仓？
            self.db.commit() # 提交一下，用新的数据库
            # 第二步被止盈 = 留20%的
            # 平仓 完成后，把所有止盈止损撤销， 然后把20%的止盈 设置在开仓前面
            suborders = self.db.query(SubOrder).filter(
                and_(SubOrder.porderid == self.order_info.orderid, SubOrder.isend == 0, SubOrder.way == 'TAKE_PROFIT_MARKET')).all()  # 需要把所有止盈订单 撤销， 留止损。 等待对手盘开仓 = 把止损取消 加止盈
            orderIdList = [int(order.orderid) for order in suborders]
            if len(orderIdList) > 0:
                # 撤销所有子订单
                self.binance.cancel_batch_order(symbol=self.order_info.symbol, orderIdList=orderIdList,
                                                origClientOrderIdList=[])

            if self.order_info is not None:
                self.order_info.status = 'PROFIT_2'
                self.order_info.twenty = 1

            self.db.commit()
            #TODO 在到达这里时 看看系统是否有挂对手盘， 帮忙挂单倒交易所

        if self.suborder_info.status == 'PROFIT_20':  # 最终结束的单子 20%
            self.db.commit()
            # 订单的终结 有俩， 1。当前方向想要继续开仓 发现有20%仓位，需要给终结掉，然后重新开单, 2. 止盈终结
            if self.order_info is not None:
                self.order_info.isend = 1
                self.order_info.twenty = 111 # 结束啦的订单
                self.order_info.aqty = '订单已结束'
                self.order_info.status = 'PROFIT_20'

                suborder_infos = self.db.query(SubOrder).filter(and_(SubOrder.porderid == self.porderid, SubOrder.isend == 0)).all()  # 查一下是否有挂单， 统统撤销
                orderIdList = []
                for suborder_info in suborder_infos:
                    orderIdList.append(int(suborder_info.orderid))

                if len(orderIdList) > 0:  # 撤销所有当前方向子订单(应该就一个止损 / 止盈订单了)
                    self.binance.cancel_batch_order(symbol=self.order_info.symbol, orderIdList=orderIdList, origClientOrderIdList=[])

            self.db.commit()

    def message_tips(self):
       # 订单类型 LIMIT 限价单  MARKET 市价单  STOP 止损限价单# STOP_MARKET 止损市价单# TAKE_PROFIT 止盈限价单# TAKE_PROFIT_MARKET 止盈市价单# TRAILING_STOP_MARKET 跟踪止损单
        order_type = '限价单' # 开单限价单
        if self.order_type == 'MARKET': # 开单市价单
            order_type = '市价单'
        if self.order_type == 'TAKE_PROFIT_MARKET': # 止盈
            order_type = '止盈'
        if self.order_type in ['STOP', 'STOP_MARKET']: # 止损
            order_type = '止损'

        if self.pside == 'LONG':
            pside = '【多头】'
        else:
            pside = '【空头】'

        message = pside

        if self.now_run_type == 'CANCELED':
            message = message + "--" + order_type + "--" + "订单已被取消: " + str(self.binance_orderid)

        if self.now_run_type == 'TRADE' and self.now_order_type == 'FILLED':  # 只需要交易 和 全部成交的订单./
            if self.pside == 'LONG':
                if self.S == 'BUY':
                    message += '订单已经成交！:' + str(self.binance_orderid)

                if self.S == 'SELL':
                    if self.order_type == 'TAKE_PROFIT_MARKET':
                        message += '订单已经止盈！' + self.status
                    if self.order_type == 'STOP_MARKET':
                        message += '订单已经止损！' + "亏损"

                    if self.order_type == 'MARKET':
                        if self.status == 'DRIVING_PROFIT_2':
                            message += '自己平仓 留20%'

                        if self.status == 'DRIVING_PROFIT_20':
                            message += '一键平仓'

            elif self.pside == 'SHORT':
                if self.S == 'SELL':
                    message += '订单已经成交！' + "成交价"

                if self.S == 'BUY':
                    if self.order_type == 'TAKE_PROFIT_MARKET':
                        message += '订单已经止盈！' + self.status
                    if self.order_type == 'STOP_MARKET':
                        message += '订单已经止损！' + "亏损"

                    if self.status == 'DRIVING_PROFIT_2':
                        message += '自己平仓 留20%'

                    if self.status == 'DRIVING_PROFIT_20':
                        message += '一键平仓'

        print("message =>", message)
        if self.now_run_type == 'TRADE' or self.now_run_type == 'CANCELED':
            requests.post('http://152.32.243.56/addRemind', json={
                "instId": self.s,
                "style": 'trade',
                "price": str(self.order_last_price),
                "side": self.pside,
                'message': message
            })

if __name__ == '__main__':
    Binance().connect()