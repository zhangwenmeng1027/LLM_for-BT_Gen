import os
from pathlib import Path

import pandas as pd
from openai import OpenAI

from BT_CSP.under_approx import BT_CSP_under_approx
from LTL4BT.LLMGen import validate_bt_list
from basic.get_process_trace import get_process_trace, get_trace_pre_cycle
from partial_P.CSP_verify import run_CSP_under_approx
from partial_P.splitN import parse_string
from basic.get_all_csp import get_all_csp
from partial_P.sketch_pre_check import list_to_string
from verify.get_neg_trace import get_neg_trace_under
import http.client
import json



Cond1 = ['atPosA', 'atPosB', 'atPosC', 'picked', 'detectionCompleted', 'placed', 'empty', 'lowBattery', 'alarm',
         'atCharge', 'taskFinishedA', 'taskFinishedB', 'hasVictim', 'hasFire',
         'storm', 'atPos3', 'atPos2', 'atPos9', 'atPos6', 'atStation', 'boxFound', 'boxNear', 'patroledA', 'patroledB',
         'patroledC', 'placedB', 'placedC', 'placed', 'noFood', 'hasApple',
         'holdKnife', 'haveData', 'unBroken', 'hasSample', 'holdItem', 'noCollision', 'isExplorationComplete',
         'targetChecked', 'processComplete', 'checkReachable', 'isDoorOpen',
         'isFull', 'TargetAdjacent', 'checkBattery', 'roomKnown', 'atRoom', 'bottleFound', 'invValid', 'bottleLocated',
         'isHungry', 'estimateCompleted', 'bottleGripped', 'atKitchen',
         'visitedA', 'visitedB', 'visitedC', 'acceptedMaterial', 'holdTools', 'abilityEvaluated', 'isTargetReached',
         'checkTimeLess5', 'isProductReady', 'isReady', 'isProcessed',
         'equalVal', 'isSearched', 'BatteryOK', 'TargetFound', 'TargetCaptured', 'hasInput', 'noDeliverTask', 'fullBattery',
         'isCharge', 'ballFound', 'ballClose', 'ballGrasped', 'binFound',
         'ballPlaced', 'robotInRoom', 'KeepArmsForGrasp', 'RobotAtInvPose', 'isOnPasture', 'isDay', 'isInShed',
         'isNight',

         ]

Act1 = ['goToPosA', 'goToPosB', 'goToPosC', 'pickUp', 'putDown', 'goToStation', 'charging', 'doTaskA', 'doTaskB',
        'doTaskC', 'doTaskD',
        'moveToTableware', 'doTaskE', 'placeB', 'placeC', 'saveVictim', 'useExtinguisher', 'moveToOtherRoom',
        'generateDetection',
        'unfoldPanels', 'searchForBox', 'closeToBox', 'Hibernate', 'foldPanels', 'getData', 'send', 'moveRight',
        'moveDown', 'move1to3','move3to2','move3to5',
        'move1to2', 'move2to3', 'move3to4', 'move4to5', 'move3to6', 'move6to9', 'move1to5', 'goToRoomC', 'patroling',
        'goToRoomB', 'goToRoomA',
        'goToKitchen', 'goToBot', 'FetchBot', 'findBot', 'askHelp', 'pickApple', 'pickKnife', 'goCow', 'killCow', 'fix',
        'analyze', 'moveToPanel', 'moveFingerToTargetPosition',
        'followOperation', 'moveToParking', 'goToStationA', 'goToStationB', 'goToStationC', 'generateNextDestination',
        'moveToDestination', 'pushR', 'acceptMaterial',
        'pushP', 'pushC', 'putOnTray', 'pickUpFromTray', 'activateProcess', 'continue', 'goToPos1', 'goToPos2',
        'goToPos3', 'goToPos4', 'goToPos5', 'goToPos6', 'goToPos7',
        'passThroughDoor', 'connectToStation', 'openDoor', 'closeDoor', 'passThroughWindow', 'findFood',
        'findTableware', 'eatfood', 'attackTarget', 'followHuman',
        'openGripper', 'closeGripper', 'locateBottle', 'fetchBottle', 'goToBottle', 'goToRoom', 'computInv',
        'testPerformance', 'evaluationPerformance', 'evaluateProcess',
        'moveTo(0-0)', 'moveTo(2-3)', 'moveTo(4-7)', 'moveTo(5-11)', 'activeManipulator', 'generateNextDestination',
        'approachTarget', 'moveToNewConfiguration','compareValue',
        'tryGrasp', 'armSleep', 'goToStateA', 'putTray', 'goToStateB', 'goToStateC', 'goToStateD', 'cleanTray',
        'acceptData', 'setValue', 'stopSearch', 'Searching',
        'Rescue', 'searchTarget', 'goToDestination', 'goToTarRoom', 'sleeping', 'waitInput', 'moveDefaultDeliverPos',
        'deliverObj', 'moveDesignPos', 'detectObj',
        'stopCharge', 'waitCharge', 'findGlass', 'fetchGlass', 'pourDrink', 'getTarget', 'randomMove', 'acceptInput',
        'searchAns', 'outputAns', 'putDownBall',
        'searchForBall', 'closeToBall','graspBall', 'goToInvPose', 'graspBottle', 'findBottle', 'SetInvPoseInvaild',
        'leaveShed', 'findRandomPastureField', 'findShed', 'enterShed',
        ]


#

import time


def LLM_BT1( ltl, llm="gpt-4o",fed = ''):

    prompt = ''' You are an expert in behavior tree (BT) synthesis and linear temporal logic (LTL). Your task is to convert LTL formulas into BT control strategies. Please focus on studying the Few-shot Demonstrations.

1. Behavior Tree Syntax
You must output the program following this strict recursive syntax:
{
    P ::= [>,r,r] | [?,r,r]
    r ::= c | a | r,r | P
    c in condition library
    a in action library
}

Control Nodes:
Sequence node > . Executes child nodes in order until one fails. The next node can only be executed when the current node returns success.
Fallback (Selector) node ? . Executes child nodes in order until one succeeds. he next node can only be executed when the current node returns failure.

Leaf Nodes:
c: A condition node from the Condition Library, with two possible return statuses: c_s and c_f, representing success and failure, respectively.
a: An action node from the Action Library, featuring three possible return statuses: a_s, a_f, and a_r, which correspond to execution success, failure, and running, respectively.

2. Node Libraries
Condition Library:
{atPosA, atPosB, atPosC, picked, detectionCompleted, placed, empty, lowBattery, alarm, atCharge, taskFinishedA, taskFinishedB, hasVictim, hasFire, storm, atPos3, atPos2, atPos9, atPos6, atStation, boxFound, boxNear, patroledA, patroledB, patroledC, placedB, placedC, noFood, hasApple, holdKnife, haveData, unBroken, hasSample, holdItem, noCollision, isExplorationComplete, targetChecked, processComplete, checkReachable, isDoorOpen, isFull, TargetAdjacent, checkBattery, roomKnown, atRoom, bottleFound, invValid, bottleLocated, isHungry, estimateCompleted, bottleGripped, InvIsComputed, atKitchen, visitedA, visitedB, visitedC, acceptedMaterial, holdTools, abilityEvaluated, isTargetReached, checkTimeLess5, isProductReady, isReady, isProcessed, equalVal, isSearched, BatteryOK, TargetFound, TargetCaptured, hasInput, noDeliverTask, fullBattery, isCharge, ballFound, ballClose, ballGrasped, binFound, ballPlaced, robotInRoom, KeepArmsForGrasp, RobotAtInvPose, isOnPasture, isDay, isInShed, isNight}

Action Library:
{goToPosA, goToPosB, goToPosC, pickUp, putDown, goToStation, charging, doTaskA,Rescue, doTaskB, move3to5,doTaskC, doTaskD, moveToTableware, doTaskE, placeB, placeC, saveVictim, useExtinguisher, moveToOtherRoom, generateDetection, unfoldPanels, searchForBox, closeToBox, Hibernate, foldPanels, getData, send, moveRight, moveDown, move1to3, move1to2, move2to3, move3to2,move3to4, move4to5, move3to6, move6to9, move1to5, goToRoomC, patroling, goToRoomB, goToRoomA, goToKitchen, goToBot, FetchBot, findBot, askHelp, pickApple, pickKnife, goCow, killCow, fix, analyze, moveToPanel, moveFingerToTargetPosition, followOperation, moveToParking, goToStationA, goToStationB, goToStationC, generateNextDestination, moveToDestination, pushR, acceptMaterial, pushP, pushC, putOnTray, pickUpFromTray, activateProcess, continue, goToPos1, goToPos2, goToPos3, goToPos4, goToPos5, goToPos6, goToPos7, passThroughDoor, connectToStation, openDoor, closeDoor, passThroughWindow, findFood, findTableware, eatfood, attackTarget, followHuman, openGripper, closeGripper, locateBottle, fetchBottle, goToBottle, goToRoom, computInv, testPerformance, evaluationPerformance, evaluateProcess, moveTo(0-0), moveTo(2-3), moveTo(4-7), moveTo(5-11), activeManipulator, approachTarget, moveToNewConfiguration, tryGrasp, armSleep, goToStateA, putTray, goToStateB, goToStateC, goToStateD, cleanTray, acceptData, setValue, compareValue, stopSearch, Searching, searchTarget, goToTarRoom, sleeping, waitInput, moveDefaultDeliverPos, deliverObj, moveDesignPos, detectObj, stopCharge, waitCharge, findGlass, fetchGlass, pourDrink, getTarget, randomMove, acceptInput, searchAns, outputAns, putDownBall, searchForBall, closeToBall, graspBall, goToInvPose, graspBottle, findBottle, SetInvPoseInvaild, leaveShed, findRandomPastureField, findShed, enterShed}

3. Constraints & Output Format
Constraint 1: The first element of every list must be a control operator: ? or >.
Constraint 2: All leaf nodes must be strings from the provided libraries.
Constraint 3: Output ONLY the resulting list structure. No "Goal" headers, no "Sketch", no explanations, and no conversational filler.
Constraint 4: If Verification Feedback is provided, analyze it silently to fix the Previous Output. Your final response must still strictly obey Constraint 3 (ONLY output the corrected list).

4. Few-shot Demonstrations
LTL: G(goToPosA_s && X(goToPosB_s|| goToPosB_f||goToPosB_r))
Output: [>, goToPosA, goToPosB]

LTL: G(goToPosA_f && X(goToPosB_s|| goToPosB_f||goToPosB_r))
Output: [?, goToPosA, goToPosB]

LTL: G(lowBattery_s -> X(goToStation_s||goToStation_f||goToStation_r)) && G(lowBattery_f && X(goToPosB_s|| goToPosB_f||goToPosB_r))
Output: [?, [>, lowBattery, goToStation], goToPosB]

# Feedback Library:
Feedback Library:

'''

    err_bt_ltl_trace = ''
    sk = ''
    if llm.startswith('gpt'):
        sk = 'sk-TCaDYHupVwuJAQrwVylDrNJJ15bUQlndblzmP6b4pWUk0aWn'
    elif llm.startswith('claude'):
        sk = 'sk-RoXVfA3Fno4VPwxU7h6MgpDjz1NAJ4m8hBbrfXuPkLjBWGMV'
    elif llm.startswith('gemini'):
        sk = 'sk-AsNI0Wz1diOy2u1d7QD7bGl0KMwTbk8g6qfXHvIpYa6Ympp3'
    else:
        # 没有匹配前缀的模型拿不到 key，直接返回，避免空跑 10 轮反馈循环
        print(f"模型 {llm} 没有匹配的 API key（名称需以 gpt/claude/gemini 开头），跳过该次调用。")
        return None, ''



    # 预处理 LTL 列表，避免在循环中重复解析
    if isinstance(ltl, str):
        ltl_list = parse_string(ltl)
    elif isinstance(ltl, list):
        ltl_list = ltl
    else:
        print(f"ltl类型错误: {type(ltl)}")
        return None,''

    # 初始化对话历史
    messages = [
        {"role": "user", "content": prompt +fed + "\n\nInstruction:"""+"\nLTL:" + ltl+ '"""'}
    ]

    max_attempts = 10

    try:
        # ----------------------------------------------------------------------------------------
        conn = http.client.HTTPSConnection("4sapi.com")
        payload = json.dumps({
            "model": llm,
            "messages": messages
        })
        headers = {
            'Accept': 'application/json',
            'Authorization': sk,
            'Content-Type': 'application/json'
        }
        conn.request("POST", "/v1/chat/completions", payload, headers)
        res = conn.getresponse()
        data = res.read()
        # print(data.decode("utf-8"))

        # ----------------------------------------------------------------------------------------
        # 1. 将字节流解码为字符串，再解析为字典
        response_dict = json.loads(data.decode("utf-8"))

        # 2. 安全地提取 content (增加了 try-except 防止报错)
        try:
            message_content = response_dict['choices'][0]['message']['content']
            # print("提取的内容：", message_content)
        except (KeyError, IndexError) as e:
            # print("解析失败，返回数据为：", response_dict)
            message_content = None
        # --------------------------------------------------------------------------------

        # 记录助手的回复，用于多轮对话上下文
        message_content = message_content.replace("\n", " ")
        # messages.append({"role": "assistant", "content": 'Error history BT and its failure traces, and the LTL property that the failure traces do not satisfy.'+message_content})

        # 修复原代码中的 replace bug（需要重新赋值）
        clean_content = message_content.replace(' ', '')
        clean_content = clean_content.replace('Output:', '')
        clean_content = clean_content.replace('output:', '').strip()

        # 1. 验证 BT 语法
        bt_list = parse_string(clean_content)
        valid, msg = validate_bt_list(bt_list)

        if not valid:
            print(f"语法验证失败: {msg}，正在反馈给 LLM...")
            # 将语法错误反馈给 LLM
            feedback_str = fed + "Previous Output: "+clean_content+"\nVerification Feedback: Syntax Error - {msg}. Please ensure your output strictly follows the required format and Node Libraries.\n"
            return None,feedback_str

        # 将BT列表转换为字符串，用于后续验证和最终输出
        str_sketch = list_to_string(bt_list)
        # print(str_sketch)

        # 2. 获取 CSP 建模并进行验证
        all_csp = get_all_csp(ltl_list, str_sketch, Cond1, Act1)
        BT_csp_under = BT_CSP_under_approx(bt_list, Cond1, Act1)
        BT_csp_under = BT_csp_under + all_csp

        verification_passed = True

        # 遍历每一个 LTL 公式进行验证
        for ltl_formula in ltl_list:
            verify_res = run_CSP_under_approx(BT_csp_under, ltl_formula, "BTcsp")

            if 'alid' not in verify_res and 'ALID' not in verify_res:
                print("PAT 工具执行异常或超时，终止验证。")
                return None, ''

            res, trace = get_neg_trace_under(verify_res)

            if not res:
                a, b, c = get_process_trace(verify_res, BT_csp_under)
                trace = get_trace_pre_cycle(a)


                feedback_str = fed + '\n{\nPrevious Output BT:'+ str_sketch +".\nFailed LTL property: "+ltl_formula+". \nCounterexample trace : "+trace +".\n}"

                return None, feedback_str

        # 如果所有 LTL 都验证通过，则成功返回
        if verification_passed:
            # print(f"验证通过！共尝试 {attempt + 1} 次。")
            print('生成目标BT程序------------------\n', str_sketch)
            return str_sketch, ''

    except Exception as e:
        print(f"LLM 交互或验证过程中发生错误: {e}")
        # 如果发生解析错误等异常，也可以尝试让模型修复自己
        return None, ''


    # print("已达到最大重试次数 (10 次)，未能生成满足约束的 BT。")
    return None,''


def main_LLM_GenBTfromLTL(llm, repeat=5):
    """对一个模型跑完整的 benchmark：repeat 遍（默认 5），每遍每个任务最多
    10 轮 LLM 生成+验证反馈；第 j 遍结束时把累计结果写入
    LLM/506-LTLtoBT_<llm>_<j>.XLSX（沿用原有累积写法：文件 j 含第 1..j 遍）。"""
    current_file = Path(__file__).resolve()

    # 项目根目录 = 当前脚本的父目录的父目录（因为 main_LTL.py 在 main_script/ 下）
    project_root = current_file.parent.parent

    # 构建文件路径
    file_path = project_root / "My_benchmark" / "My_benchmark.xlsx"
    # file_path = r"/home/hps/Desktop/BTLTL/My_benchmark/My_benchmark1.xlsx"
    # 检查文件是否存在
    if not os.path.exists(file_path):
        print(f"found file error {file_path}")
        return
    # Cond = ['holdKnife','atPosA','atPosB','atPosC','atPos3']00..
    # Act = ['doTaskA','doTaskB','doTaskC','goToKitchen','acceptInput','moveFingerToTargetPosition','goToPosA','goToPosB','goToPosC','goToPos3']

    timeout_seconds = 360
    results = []
    try:
        # 读取Excel文件
        # 注意：这里使用 pd.read_excel，确保 pd 是 pandas 模块
        df = pd.read_excel(file_path, header=0, usecols=[0, 1, 2])

        # 遍历每一行数据
        j = 0
        while j < repeat:
            j += 1
            for row in df.itertuples(index=False):
                # 处理可能为空的数据
                task_name = str(row[0]) if pd.notna(row[0]) else "无任务名"
                description = str(row[1]) if pd.notna(row[1]) else "doTask"
                ltl_content = str(row[2]) if pd.notna(row[2]) else " "
                bt_result = None
                start_time = time.time()
                num = -1
                print(task_name)
                fed = ''
                for i in range(10):
                    i += 1
                    bt_result,fed = LLM_BT1(ltl_content, llm,fed)
                    if bt_result is not None:
                        num = i
                        break
                # print(bt_result)
                end_time = time.time()
                execution_time = end_time - start_time
                results.append({
                    'Task': task_name,
                    'LTL': ltl_content,
                    'BT_Result': bt_result,
                    'Num':num,
                    'time': execution_time
                })
                print('--------------------------')

            # 将结果保存到result.XLSX文件
            result_df = pd.DataFrame(results)
            result_dir = project_root / 'LLM'
            result_dir.mkdir(parents=True, exist_ok=True)   # 目录不存在时先创建
            result_path = result_dir / f"506-LTLtoBT_{llm}_{j}.XLSX"
            result_df.to_excel(result_path, index=False, engine='openpyxl')
            print(f"结果已保存到 {result_path}")


    except AttributeError as e:
        print(f"Error: {e}")
        # print("请检查是否在代码其他地方定义了名为 'pd' 或 'pandas' 的函数。")
    except Exception as e:
        print(f"Error: {e}")















if __name__ == "__main__":

    bt = '[?, [>, alarm, [?, taskFinishedB, [>, atPosA, doTaskA], [>, goToPosA, doTaskA]]], [?, [?, taskFinishedB, [>, atPosB, doTaskB], [>, goToPosB, doTaskB]]]]'
    ltl = '[X(lowBattery_s || lowBattery_f) && G(lowBattery_s -> X(invValid_s || invValid_f)), G(invValid_f -> X(computInv_s || computInv_f || computInv_r)), G(invValid_s -> X(acceptInput_s || acceptInput_f || acceptInput_r)) && G(acceptInput_s -> X(searchAns_s || searchAns_f || searchAns_r)), G(roomKnown_s -> X(goToRoom_s || goToRoom_f || goToRoom_r)) && G(goToRoom_s -> X(sleeping_s || sleeping_f || sleeping_r)), G(atKitchen_s -> X(doTaskA_s || doTaskA_f || doTaskA_r)),G(alarm_s -> X(holdTools_s || holdTools_f)) && G(holdTools_s -> X(goToKitchen_s || goToKitchen_f || goToKitchen_r)), G(goToKitchen_s -> X(useExtinguisher_s || useExtinguisher_f || useExtinguisher_r|| doTaskA_s || doTaskA_f || doTaskA_r))]'

    LTL = parse_string(ltl)
    task = 'The robot chooses to perform the following tasks:Task 1: Firstly, Check if the current battery level has reached a low state, and then calculate the value of inv or if the inv value has already been calculated. Then accept the input value and search for the answer. If the robot knows the room number, it moves to that room and enters sleep mode.Secondly, Check if the robot is already in the kitchen or moving to the kitchen. Finally, execute task A.Task 2: When the alarm sounds, check if you are holding a tool and navigate to the kitchen to use a fire extinguisher.Task 3: Wait for charging.'
    # LLM_BT1(task,ltl)

    # ---- 多模型 CLI：--model 逗号分隔多个模型，依次各跑 --repeat 遍 ------------
    # 例：python LTLtoBT.py --model gpt-4o,gpt-5.5,claude-opus-4-6 --repeat 5
    import argparse
    ap = argparse.ArgumentParser(description='LTL->BT 生成实验（支持一次跑多个模型）')
    ap.add_argument('--model', default='gpt-4o,claude-opus-4-6',
                    help='模型名或逗号分隔列表，如 gpt-4o,gpt-5.5；API key 按前缀 '
                         'gpt/claude/gemini 自动匹配（默认: %(default)s）')
    ap.add_argument('--repeat', type=int, default=5,
                    help='每个模型重复跑几遍（默认 5，即原来的 while j<5）')
    args = ap.parse_args()

    models = [m.strip() for m in args.model.split(',') if m.strip()]
    for idx, model in enumerate(models, 1):
        print('\n############ model {} ({}/{}) ############'.format(model, idx, len(models)))
        main_LLM_GenBTfromLTL(model, repeat=args.repeat)
    print('\nAll done: {} model(s) x {} repeat(s)'.format(len(models), args.repeat))
