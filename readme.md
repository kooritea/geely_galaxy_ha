# 吉利银河 app 车辆控制接入ha 自定义集成

支持开关门(不包含蓝牙钥匙)、开关空调、传感器显示、位置显示
只测试过单一车型，欢迎测试

# 安装
[![通过HACS添加集成](https://my.home-assistant.io/badges/hacs_repository.svg)][hacs]

# 登录
需要手机app抓包
- 手机app在登录页面点击获取验证码(暂不登录)
- 然后开始抓包
- 输入验证码点击登录
- 抓包软件找到/api/v1/login/mobileCodeLogin的响应体获取refreshToken和hardwareDeviceId
- 在ha中开始集成配置输入这两个值

# 代码实现参考了下面的仓库(不分先后)
- https://github.com/Jiran-sama/geely-panda
- https://github.com/suyunkai/geely-galaxy-assistant

[hacs]: https://my.home-assistant.io/redirect/hacs_repository/?owner=kooritea&repository=geely_galaxy_ha&category=integration