import torch
import torch.nn as nn
import torch.nn.functional as F
import math

if 'sinc' in dir(torch):
    sinc = torch.sinc
else:
    # This code is adopted from adefossez's julius.core.sinc
    # https://adefossez.github.io/julius/julius/core.html
    def sinc(x: torch.Tensor):
        """
        Implementation of sinc, i.e. sin(pi * x) / (pi * x)
        __Warning__: Different to julius.sinc, the input is multiplied by `pi`!
        """
        return torch.where(x == 0,
                           torch.tensor(1., device=x.device, dtype=x.dtype),
                           torch.sin(math.pi * x) / math.pi / x)


# This code is adopted from adefossez's julius.lowpass.LowPassFilters
# https://adefossez.github.io/julius/julius/lowpass.html


#return filter [1,1,kernel_size]
def kaiser_sinc_filter1d(cutoff, half_width, kernel_size):
    even = (kernel_size % 2 == 0)
    half_size = kernel_size // 2

    #For kaiser window
    delta_f = 4 * half_width
    A = 2.285 * (half_size - 1) * math.pi * delta_f + 7.95
    if A > 50.:
        beta = 0.1102 * (A - 8.7)
    elif A >= 21.:
        beta = 0.5842 * (A - 21)**0.4 + 0.07886 * (A - 21.)
    else:
        beta = 0.
    window = torch.kaiser_window(kernel_size, beta=beta, periodic=False)
    #ratio = 0.5/cutoff -> 2 * cutoff = 1 / ratio
    if even:
        time = (torch.arange(-half_size, half_size) + 0.5)
    else:
        time = torch.arange(kernel_size) - half_size
    if cutoff == 0:
        filter_ = torch.zeros_like(time)
    else:
        filter_ = 2 * cutoff * window * sinc(2 * cutoff * time)
        # Normalize filter to have sum = 1, otherwise we will have a small leakage
        # of the constant component in the input signal.
        filter_ /= filter_.sum()
        filter = filter_.view(1, 1, kernel_size)
    return filter


class LowPassFilter1d(nn.Module):

    def __init__(self,
                 cutoff=0.5,
                 half_width=0.6,
                 stride: int = 1,
                 padding: bool = True,
                 padding_mode: str = 'replicate',
                 kernel_size: int = 12):
        # kernel_size should be even number for stylegan3 setup,
        # in this implementation, odd number is also possible.
        super().__init__()
        if cutoff < -0.:
            raise ValueError("Minimum cutoff must be larger than zero.")
        if cutoff > 0.5:
            raise ValueError("A cutoff above 0.5 does not make sense.")
        self.kernel_size = kernel_size
        self.even = (kernel_size % 2 == 0)
        self.pad_left = kernel_size // 2 - int(self.even)
        self.pad_right = kernel_size // 2
        self.stride = stride
        self.padding = padding
        self.padding_mode = padding_mode
        filter = kaiser_sinc_filter1d(cutoff, half_width, kernel_size)
        self.register_buffer("filter", filter)

    #input [B,C,T]
    def forward(self, x):
        _, C, _ = x.shape
        if self.padding:
            x = F.pad(x, (self.pad_left, self.pad_right),
                      mode=self.padding_mode)
        out = F.conv1d(x, self.filter.expand(C, -1, -1),
                       stride=self.stride, groups=C)
        return out


def kaiser_sinc_filter2d(cutoff, half_width, kernel_size):
    even = (kernel_size % 2 == 0)
    half_size = kernel_size // 2
    #For kaiser window
    delta_f = 4 * half_width
    A = 2.285 * (half_size - 1) * math.pi * delta_f + 7.95
    if A > 50.:
        beta = 0.1102 * (A - 8.7)
    elif A >= 21.:
        beta = 0.5842 * (A - 21)**0.4 + 0.07886 * (A - 21.)
    else:
        beta = 0.

    #rotation equivariant grid
    if even:
        time = torch.stack(torch.meshgrid(
            torch.arange(-half_size, half_size) + 0.5,
            torch.arange(-half_size, half_size) + 0.5),
            dim=-1)
    else:
        time = torch.stack(torch.meshgrid(
            torch.arange(kernel_size) - half_size,
            torch.arange(kernel_size) - half_size),
            dim=-1)

    time = torch.norm(time, dim=-1)
    #rotation equivariant window
    window = torch.i0(
        beta * torch.sqrt(1 - (time / half_size / 2**0.5)**2)) / torch.i0(
            torch.tensor([beta]))
    #ratio = 0.5/cutroff
    if cutoff == 0:
        filter_ = torch.zeros_like(time)
    else:
        filter_ = 2 * cutoff * window * sinc(2 * cutoff * time)
        # Normalize filter to have sum = 1, otherwise we will have a small leakage
        # of the constant component in the input signal.
        filter_ /= filter_.sum()
        filter = filter_.view(1, 1, kernel_size, kernel_size)
    return filter


class LowPassFilter2d(nn.Module):

    def __init__(self,
                 cutoff=0.5,
                 half_width=0.6,
                 stride: int = 1,
                 padding: bool = True,
                 padding_mode: str = 'replicate',
                 kernel_size: int = 12):
        # kernel_size should be even number for stylegan3 setup,
        # in this implementation, odd number is also possible.
        super().__init__()
        if cutoff < -0.:
            raise ValueError("Minimum cutoff must be larger than zero.")
        if cutoff > 0.5:
            raise ValueError("A cutoff above 0.5 does not make sense.")
        self.kernel_size = kernel_size
        self.even = (kernel_size % 2 == 0)
        self.pad_left = kernel_size // 2 - int(self.even)
        self.pad_right = kernel_size // 2
        self.stride = stride
        self.padding = padding
        self.padding_mode = padding_mode
        filter = kaiser_sinc_filter2d(cutoff, half_width, kernel_size)
        self.register_buffer("filter", filter)

    #input [B,C,W,H]
    def forward(self, x):
        _, C, _, _ = x.shape
        if self.padding:
            x = F.pad(
                x,
                (self.pad_left, self.pad_right, self.pad_left, self.pad_right),
                mode=self.padding_mode,
            )
        out = F.conv2d(x, self.filter.expand(C, -1, -1, -1),
                       stride=self.stride, groups=C)
        return out
    
def kaiser_sinc_filter3d(cutoff, half_width, kernel_size):
    even = (kernel_size % 2 == 0)
    half_size = kernel_size // 2

    delta_f = 4 * half_width
    A = 2.285 * (half_size - 1) * math.pi * delta_f + 7.95
    if A > 50.:
        beta = 0.1102 * (A - 8.7)
    elif A >= 21.:
        beta = 0.5842 * (A - 21)**0.4 + 0.07886 * (A - 21.)
    else:
        beta = 0.
    
    if even:
        time = (torch.arange(-half_size, half_size) + 0.5)
    else:
        time = torch.arange(kernel_size) - half_size
    if cutoff == 0:
        filter_ = torch.zeros_like(time)
    else:
        filter_ = 2 * cutoff * sinc(2 * cutoff * time)
        filter_ *= torch.i0(beta * torch.sqrt(1 - (time / half_size / 2**0.5)**2)) / torch.i0(torch.tensor([beta]))
        filter_ /= filter_.sum()
        filter = filter_.view(1, 1, 1, kernel_size)
    return filter

class LowPassFilter3d(nn.Module):

    def __init__(self,
                 cutoff=0.5,
                 half_width=0.6,
                 stride: int = 1,
                 padding: bool = True,
                 padding_mode: str = 'replicate',
                 kernel_size: int = 12):
        super().__init__()
        
        if cutoff < -0.:
            raise ValueError("Minimum cutoff must be larger than zero.")
        if cutoff > 0.5:
            raise ValueError("A cutoff above 0.5 does not make sense.")
        
        self.kernel_size = kernel_size
        self.even = (kernel_size % 2 == 0)
        self.pad_left = kernel_size // 2 - int(self.even)
        self.pad_right = kernel_size // 2
        self.stride = stride
        self.padding = padding
        self.padding_mode = padding_mode
        filter = kaiser_sinc_filter3d(cutoff, half_width, kernel_size)
        self.register_buffer("filter", filter)

    def forward(self, x):
        _, C, _, _, _ = x.shape
        if self.padding:
            x = F.pad(
                x,
                (self.pad_left, self.pad_right, self.pad_left, self.pad_right,
                 self.pad_left, self.pad_right),
                mode=self.padding_mode,
            )
        out = F.conv3d(x, self.filter.expand(C, -1, -1, -1, -1),
                       stride=self.stride, groups=C)
        return out
