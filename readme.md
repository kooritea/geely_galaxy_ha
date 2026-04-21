# 吉利银河 app 车辆控制接入ha 自定义集成

支持开关门(不包含蓝牙钥匙)、开关空调、传感器显示、位置显示
只测试过单一车型，欢迎测试

# 安装
[![通过HACS添加集成](https://my.home-assistant.io/badges/hacs_repository.svg)][hacs]

# 登录
建议把车辆分享给小号，登录小号抓包给ha登录。ha和app登录同一个账号会互相触发对方刷新token,可能会掉登录。

需要手机app抓包
- 手机app在登录页面点击获取验证码(暂不登录)
- 然后开始抓包
- 输入验证码点击登录
- 抓包软件找到/api/v1/login/mobileCodeLogin的响应体获取refreshToken和hardwareDeviceId
- 在ha中开始集成配置输入这两个值
- (如果是使用小号登录ha的话)不要点击app里的退出登录，去系统设置里面清除应用数据或者卸载app重新安装来退出登录

# 代码实现参考了下面的仓库(不分先后)
- https://github.com/Jiran-sama/geely-panda
- https://github.com/suyunkai/geely-galaxy-assistant

[hacs]: https://my.home-assistant.io/redirect/hacs_repository/?owner=kooritea&repository=geely_galaxy_ha&category=integration