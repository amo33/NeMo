import os
from functools import cache
from typing import List, Optional

import torch
from megatron.core.utils import check_param_hashes_across_dp_replicas
from pytorch_lightning.callbacks.callback import Callback

from nemo.lightning import io
from nemo.utils import logging
from nemo.utils.get_rank import get_rank


@cache
def pl_has_dist_opt_with_ovelap(trainer):
    optim_config = getattr(getattr(trainer.strategy.model, 'optim', None), 'config', None)
    if not getattr(optim_config, 'use_distributed_optimizer', False):
        return False
    if not getattr(optim_config, 'overlap_param_gather', False):
        return False
    return True


def pl_check_param_hashes_across_dp_replicas(trainer):
    if pl_has_dist_opt_with_ovelap(trainer):
        for opt in self.optimizers:
            opt.disable_pre_hook()

    torch.distributed.barrier()
    res = check_param_hashes_across_dp_replicas([trainer.strategy.model])
    torch.distributed.barrier()

    if pl_has_dist_opt_with_ovelap(trainer):
        for opt in self.optimizers:
            opt.disable_pre_hook()
    return res


class DdpParamParityChecker(Callback, io.IOMixin):
    """
    This callback enables weight parity checkping across DDP replicas with Mcore models.

    User can specify their desired interval for weights to be checked via the `interval` parameter.

    Args:
        dir (Optional[str]): Directory to store the memory profile dump

    Example:
        >>> callback = DdpParamParityChecker(interval=10)
        >>> trainer = Trainer(callbacks=[callback])
    """

    def __init__(self, interval: int = 0):
        """
        interval (int): How frequently to check DDP weights for errors. Default to 0 (off).
        """
        assert interval > 0, "Expected interval to be > 0. A zero interval makes DdpParamParityChecker a no-op."
        self.interval = interval
        self.step = 0

    def on_train_batch_start(self, trainer, pl_module, batch, batch_idx, unused=0) -> None:
        if self.step == self.interval - 1:
            if pl_check_param_hashes_across_dp_replicas(trainer):
                logging.info(f"DDP Param parity check passed for batch-id= {batch_idx}")
            else:
                raise RuntimeError(f"DDP Param parity check FAILED for batch-id= {batch_idx}")
        self.step = (self.step + 1) % self.interval

    def on_train_end(self, trainer, pl_module) -> None:
        pl_check_param_hashes_across_dp_replicas(trainer)
        logging.info("DDP Param parity check passed at end of training.")
