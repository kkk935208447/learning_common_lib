from typing import List
from math import inf
from random import choice
from collections import Counter


class Solution:
    def threeSum(self, nums: list[int]) -> list[list[int]]:
        # 排序+ 双端指针 + 两次去重,  固定首字，判断后三个数相加 与 0 的大小

        nums = sorted(nums)
        print(nums)

        res = []
        for idx, n in enumerate(nums[:-2]):
            if idx >=1 and nums[idx] == nums[idx-1]:
                continue  # 第一次去重
            
            L = idx + 1
            R = len(nums)-1
            while L < R:
                print(L, R)
                if n + nums[L] + nums[R] == 0:
                    res.append([n, nums[L], nums[R]])
                    L += 1
                    print(L)
                    while nums[L] == nums[L-1]:
                        L += 1
                elif n + nums[L] + nums[R] < 0:
                    L += 1
                else:
                    R -= 1
            return res
            

if __name__ == "__main__":
    solution = Solution()
    print(solution.threeSum([0, 0, 0]))