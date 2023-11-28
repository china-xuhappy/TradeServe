# # 交易数据库 操作
from sqlalchemy import and_, Column, String, Integer, create_engine, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base

# 创建对象的基类:
Base = declarative_base()

class Order(Base):
    __tablename__ = 'orders'

    orderid = Column(String(200), primary_key=True) # 交易所ID
    cust_orderid = Column(String(200)) # 自定义ID
    symbol = Column(String(20), nullable=False) # 交易对
    # side = Column(String(20), nullable=False) # 手续费

    side = Column(String(20), nullable=False)
    price = Column(String(20), nullable=False)
    tqty = Column(String(20), nullable=False)
    aqty = Column(String(20), nullable=False)
    margin = Column(String(20), nullable=False, default='200')
    isend = Column(Integer, nullable=False, default=2) # 整单是否完结？ 0已开始 - 未完结，1已开始-完结，2未开始 挂单，3未开始 撤销
    status = Column(String(20), nullable=False, default='START')
    twenty = Column(Integer, nullable=False, default=0) #  '1 = 20， 0 != 不是20'
    plstatus = Column(String(20), nullable=False, default='进行中')
    placcount = Column(String(20), nullable=False, default='0.0')
    remark = Column(String(1000), nullable=True, default='')
    way = Column(String(20), nullable=False, default='MARKET')

    # sub_orders = relationship("SubOrder", back_populates="parent_order")

class SubOrder(Base):
    __tablename__ = 'suborder'

    orderid = Column(String(200), primary_key=True)
    porderid = Column(String(200))
    way = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False)
    tstatus = Column(String(50), nullable=False)
    qty = Column(String(50), nullable=False)
    price = Column(String(50), nullable=False)
    rp = Column(String(50), nullable=False)
    side = Column(String(50), nullable=False)
    bs = Column(String(50), nullable=False)

    isend = Column(Integer, nullable=False, default=0) # 0挂单，1已触发，2已撤销（失效）
    # 建立与父表Order的关联关系
    # parent_order = relationship("Order", back_populates="sub_orders")

# engine = create_engine('mysql+pymysql://xuhappy:Xu015106@rm-bp1e8nn46n6ce698tro.mysql.rds.aliyuncs.com:3306/trade')
# # 创建DBSession类型:
# DBSession = sessionmaker(bind=engine)
# db = DBSession()
# order_progress = db.query(Order).filter(and_(Order.symbol == 'BTCUSDT',Order.isend==0)).all() # 查询进行中的订单
# print(order_progress)