# 本地验证状态

执行环境：Windows，Python 3.11，PowerContext 1.2.0，pytest 8.4.2。

`python -m pytest tests -q --junitxml=evidence/local/workflow.xml`
退出码 0：2 passed。覆盖真实 PowerContext 两个独立进程之间的状态写入、读取
及引用一致性，并检查业务基线失败确实来自目标功能断言。

业务基线：14 failed、3 passed；退出码 1。14 个目标功能用例失败，3 个原有
行为回归用例通过，没有环境错误。详见 tests-before.json 和 before.xml。

MiniMax 调用、seekdb/OceanBase 实际查询、模型修改后的同组测试、完整上下文
恢复及规格重导入尚未实测。这里的通过结果不代表比赛验收通过。
